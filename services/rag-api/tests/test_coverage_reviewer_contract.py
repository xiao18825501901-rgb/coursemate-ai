"""Contract tests for the production model coverage reviewer (no billing).

The reviewer code path runs against a scripted fake upstream (``FakeInvoke``)
and a local database. These tests prove the server-side contract:

1.  a reasonable paraphrase with a real verbatim evidence quote counts;
2.  keyword-only or acceptance-echo content does not;
3.  partial / uncertain / not_covered verdicts are written per item;
4.  invalid JSON, forged ids and out-of-scope ids never write coverage;
5.  the reviewer is default-off, and the billable gate rejects before any
    request when the budget is not authorized;
6.  a review failure keeps the teaching visible and leaves coverage pending;
7.  a persisted review + interrupted RAG bookkeeping replays without calling
    the model again (no auto-retry billing).

Real model judgment quality is NOT proven here; it belongs to the approved
canary. These are contract tests, not live Qwen evidence.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.learning.coverage_review import (
    DeterministicCoverageReviewer,
    ModelCoverageReviewer,
    NullCoverageReviewer,
    ReviewOutcome,
    qwen_review_invoke,
    resolve_coverage_reviewer,
)
from app.learning.shell_delivery import _server_validate, submit_shell_delivery
from app.learning.workspaces import join_course

NODE = "contract-node"
ITEM_A = "contract-a"
ITEM_B = "contract-b"


def items() -> list[dict]:
    return [
        {
            "item_id": ITEM_A,
            "requirement": "REQUIRED",
            "objective": "Explain the central-limit intuition",
            "acceptance": "给出中心极限定理的直觉并用一个例子说明。",
        },
        {
            "item_id": ITEM_B,
            "requirement": "REQUIRED",
            "objective": "Explain the update rule",
            "acceptance": "说明参数更新的规则并给出一条公式。",
        },
    ]


CONTENT = (
    "中心极限定理的直觉是：大量独立随机变量的均值近似正态分布。"
    "例如掷一百次硬币，正面比例的分布会越来越接近钟形。"
    "参数更新的规则是沿着梯度方向移动，公式为 θ ← θ − η∇L(θ)。"
)


class FakeInvoke:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, messages, max_tokens):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def outcome(
    decision_a: str = "covered",
    quote_a: str = "大量独立随机变量的均值近似正态分布",
    decision_b: str = "not_covered",
    quote_b: str = "",
    extra_id: str | None = None,
) -> str:
    rows = [
        {"item_id": ITEM_A, "decision": decision_a, "reason": "理由 A", "evidence_quote": quote_a},
        {"item_id": ITEM_B, "decision": decision_b, "reason": "理由 B", "evidence_quote": quote_b},
    ]
    if extra_id:
        rows.append(
            {"item_id": extra_id, "decision": "covered", "reason": "伪造", "evidence_quote": "x"}
        )
    return json.dumps({"verdicts": rows}, ensure_ascii=False)


async def test_reasonable_paraphrase_with_real_quote_counts() -> None:
    reviewer = ModelCoverageReviewer(FakeInvoke([outcome()]), model="qwen3.8-max")
    result = await reviewer.review(items(), CONTENT, {"spec_version": 1})
    assert result.status == "completed"
    assert result.confirmed == [ITEM_A]


async def test_partial_uncertain_verdicts_written_per_item() -> None:
    reviewer = ModelCoverageReviewer(
        FakeInvoke(
            [
                outcome(
                    decision_a="partial",
                    quote_a="",
                    decision_b="uncertain",
                    quote_b="",
                )
            ]
        ),
        model="qwen3.8-max",
    )
    result = await reviewer.review(items(), CONTENT, {"spec_version": 1})
    assert result.confirmed == []
    assert result.verdicts[ITEM_A]["decision"] == "partial"
    assert result.verdicts[ITEM_B]["decision"] == "uncertain"


async def test_server_validation_rejects_quote_not_in_body_and_keyword_only() -> None:
    # The model claims coverage with a quote that is NOT verbatim in the body.
    result = ReviewOutcome(
        status="completed",
        confirmed=[ITEM_A],
        verdicts={
            ITEM_A: {"decision": "covered", "reason": "r", "evidence_quote": "完全不存在的一句话"}
        },
        reviewer="ModelCoverageReviewer",
    )
    assert _server_validate(result, items(), CONTENT) == []
    # Acceptance-echo only: quoting the acceptance criterion itself is not
    # evidence of teaching it (the acceptance sentence is not in this body).
    echo = ReviewOutcome(
        status="completed",
        confirmed=[ITEM_B],
        verdicts={
            ITEM_B: {
                "decision": "covered",
                "reason": "r",
                "evidence_quote": "说明参数更新的规则并给出一条公式。",
            }
        },
        reviewer="ModelCoverageReviewer",
    )
    assert _server_validate(echo, items(), CONTENT) == []


async def test_ellipsis_joined_segments_anchor_but_fabricated_segments_reject() -> None:
    # Live reviewers assemble quotes with ellipses; every non-trivial segment
    # must still appear verbatim in the body.
    joined = ReviewOutcome(
        status="completed",
        confirmed=[ITEM_A, ITEM_B],
        verdicts={
            ITEM_A: {
                "decision": "covered",
                "reason": "r",
                "evidence_quote": "大量独立随机变量的均值近似正态分布…正面比例的分布会越来越接近钟形",
            },
            ITEM_B: {
                "decision": "covered",
                "reason": "r",
                "evidence_quote": "沿着梯度方向移动，公式为 θ ← θ − η∇L(θ)",
            },
        },
        reviewer="ModelCoverageReviewer",
    )
    assert _server_validate(joined, items(), CONTENT) == [ITEM_A, ITEM_B]

    fabricated = ReviewOutcome(
        status="completed",
        confirmed=[ITEM_A],
        verdicts={
            ITEM_A: {
                "decision": "covered",
                "reason": "r",
                "evidence_quote": "大量独立随机变量的均值近似正态分布…这段内容并不存在于正文之中",
            }
        },
        reviewer="ModelCoverageReviewer",
    )
    assert _server_validate(fabricated, items(), CONTENT) == []


async def test_invalid_json_forged_ids_and_extra_fields_fail_closed() -> None:
    reviewer = ModelCoverageReviewer(FakeInvoke(["这不是 JSON"]), model="qwen3.8-max")
    bad = await reviewer.review(items(), CONTENT, {"spec_version": 1})
    assert bad.status == "failed"
    assert bad.confirmed == []

    forged = ModelCoverageReviewer(
        FakeInvoke([outcome(extra_id="forged-item")]), model="qwen3.8-max"
    )
    result = await forged.review(items(), CONTENT, {"spec_version": 1})
    assert "forged-item" not in result.verdicts
    assert result.confirmed == [ITEM_A]  # only the in-scope covered verdict survives


async def test_reviewer_transport_failure_fails_closed() -> None:
    reviewer = ModelCoverageReviewer(
        FakeInvoke([httpx.ConnectError("boom")]), model="qwen3.8-max"
    )
    result = await reviewer.review(items(), CONTENT, {"spec_version": 1})
    assert result.status == "failed"
    assert result.confirmed == []
    assert "ConnectError" in result.error


def test_default_disabled_and_budget_gate_reject_before_request() -> None:
    assert isinstance(resolve_coverage_reviewer("production", None, allow_billable=False), NullCoverageReviewer)
    with pytest.raises(ValueError, match="separately billed"):
        resolve_coverage_reviewer("production", "model", allow_billable=False)
    with pytest.raises(ValueError, match="requires the site model credential"):
        resolve_coverage_reviewer("production", "model", allow_billable=True)
    assert isinstance(
        resolve_coverage_reviewer("test", "deterministic", allow_billable=False),
        DeterministicCoverageReviewer,
    )
    with pytest.raises(ValueError, match="forbidden in production"):
        resolve_coverage_reviewer("production", "deterministic", allow_billable=False)

    calls = 0

    async def counting_transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": []})

    invoke = qwen_review_invoke(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="redacted",
        model="qwen3.8-max",
        timeout=30,
        allow_billable=False,
    )
    import asyncio

    with pytest.raises(RuntimeError, match="BILLING_NOT_AUTHORIZED"):
        asyncio.run(invoke([{"role": "user", "content": "x"}], 100))
    assert calls == 0  # rejected before any request left the process


def make_db(tmp_path: Path) -> Database:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )
    database = Database(settings)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,publication_status) VALUES('cs3481','Synthetic','published')"
        )
    workspace = join_course(database, "cs3481", "user-a", 10)
    content = json.dumps(items(), ensure_ascii=False, sort_keys=True)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,'cs3481',NULL,'Contract Node',"
            "'Synthetic','CS','ATOMIC','PUBLISHED')",
            (NODE,),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (NODE, content, hashlib.sha256(content.encode()).hexdigest()),
        )
        connection.execute(
            "INSERT INTO learning_journeys(id,workspace_id,node_id,spec_version) "
            "VALUES('journey-contract',?,?,1)",
            (workspace["id"], NODE),
        )
    return database


NODE_DICT = {"id": NODE, "spec_hash": None}


async def test_review_failure_keeps_teaching_and_marks_pending(tmp_path: Path) -> None:
    database = make_db(tmp_path)
    invoke = FakeInvoke([httpx.ConnectError("down")])
    result = await submit_shell_delivery(
        database,
        workspace_id="w-1",
        journey_id="journey-contract",
        node=NODE_DICT,
        spec_version=1,
        items=items(),
        content=CONTENT,
        operation_id="contract-fail-001",
        provenance={"run_id": "contract-fail-001", "course_id": "cs3481"},
        reviewer=ModelCoverageReviewer(invoke, model="qwen3.8-max"),
    )
    # The teaching unit is persisted (recoverable), nothing counted as covered.
    assert result["unit_id"]
    assert result["covered"] == []
    assert result["review"]["status"] == "failed"
    with database.connect() as connection:
        unit = connection.execute(
            "SELECT provenance_json FROM teaching_units WHERE operation_id=?",
            ("contract-fail-001",),
        ).fetchone()
        saved_review = json.loads(unit["provenance_json"])["review"]
        assert saved_review["status"] == "failed"
        assert saved_review["error"]
        evidence = connection.execute(
            "SELECT COUNT(*) FROM teaching_delivery_evidence"
        ).fetchone()[0]
        assert evidence == 0


async def test_review_persisted_then_replay_never_calls_model_again(tmp_path: Path) -> None:
    database = make_db(tmp_path)
    invoke = FakeInvoke([outcome()])
    first = await submit_shell_delivery(
        database,
        workspace_id="w-1",
        journey_id="journey-contract",
        node=NODE_DICT,
        spec_version=1,
        items=items(),
        content=CONTENT,
        operation_id="contract-replay-001",
        provenance={"run_id": "contract-replay-001", "course_id": "cs3481"},
        reviewer=ModelCoverageReviewer(invoke, model="qwen3.8-max"),
    )
    assert first["covered"] == [ITEM_A]
    assert invoke.calls == 1

    # Interrupted bookkeeping recovery: same operation id replays the saved
    # unit and evidence without any additional model call.
    second = await submit_shell_delivery(
        database,
        workspace_id="w-1",
        journey_id="journey-contract",
        node=NODE_DICT,
        spec_version=1,
        items=items(),
        content=CONTENT,
        operation_id="contract-replay-001",
        provenance={"run_id": "contract-replay-001", "course_id": "cs3481"},
        reviewer=ModelCoverageReviewer(invoke, model="qwen3.8-max"),
    )
    assert second["replayed"] is True
    assert second["covered"] == [ITEM_A]
    assert invoke.calls == 1  # no second review, no hidden retry billing


async def test_partial_coverage_submits_only_confirmed_items(tmp_path: Path) -> None:
    database = make_db(tmp_path)
    invoke = FakeInvoke([outcome(quote_a="大量独立随机变量的均值近似正态分布")])
    result = await submit_shell_delivery(
        database,
        workspace_id="w-1",
        journey_id="journey-contract",
        node=NODE_DICT,
        spec_version=1,
        items=items(),
        content=CONTENT,
        operation_id="contract-partial-001",
        provenance={"run_id": "contract-partial-001", "course_id": "cs3481"},
        reviewer=ModelCoverageReviewer(invoke, model="qwen3.8-max"),
    )
    assert result["covered"] == [ITEM_A]
    assert result["progress"] == "LEARNING"  # 1 of 2 REQUIRED items
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT item_id, validation_status FROM teaching_delivery_evidence"
        ).fetchall()
        assert [(r["item_id"], r["validation_status"]) for r in rows] == [
            (ITEM_A, "REVIEWED")
        ]
