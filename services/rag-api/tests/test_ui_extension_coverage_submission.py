"""The real coverage closure: completed shell teaching -> V3 evidence ledger.

Closure prompt 2.3 acceptance, run from ZERO coverage with no pre-seeded
evidence: partial coverage yields LEARNING, full REQUIRED coverage yields
LEARNED, assessment stays independent, and failed / cancelled / truncated /
keyword-only / wrong-user / stale-spec inputs never count.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.learning.coverage_review import DeterministicCoverageReviewer
from app.learning.workspaces import join_course
from app.main import create_app

UI = "/ui-extension/api/ui/v1"
NODE = "cov-zero"
ITEM_A = "cov-item-a"
ITEM_B = "cov-item-b"

SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class ScriptedProvider:
    """Answers teach runs with pre-scripted content; records every call."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, **kwargs):
        self.calls.append({"lane": lane, "text": text, "bridge": bridge, "kwargs": kwargs})
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        yield {"kind": "status", "status": "planning", "label": "测试模型"}
        yield {"kind": "prompt", "text": "本地测试 Prompt（非千问实测）"}
        yield {"kind": "status", "status": "generating", "label": "测试模型"}
        yield {"kind": "delta", "text": answer or "## Step 1 审题\n识别条件与目标。"}
        yield {"kind": "usage", "stage": "answer", "value": {"output_tokens": 2}}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        admin_user_ids="user-admin",
        app_env="test",
        v3_enabled=True,
        ui_extension_enabled=True,
        rag_provider_mode="deterministic",
        ui_web_dir=tmp_path / "no-web-build",
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    provider = ScriptedProvider([])
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider,
        ui_coverage_reviewer=DeterministicCoverageReviewer(),
    )
    with TestClient(application) as test_client:
        from campus_actor_fixture import authorize_synthetic_campus_users
        authorize_synthetic_campus_users(test_client, 'user-a', 'user-b')
        test_client.app.state.ui_provider = provider  # type: ignore[attr-defined]
        seed_course_and_node(test_client)
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


def seed_course_and_node(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        headers=auth("Bearer admin-token"),
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    database = client.app.state.database
    join_course(database, "cs3481", "user-a", 10)
    content = json.dumps(
        [
            {
                "item_id": ITEM_A,
                "requirement": "REQUIRED",
                "objective": "Explain concept A",
                "acceptance": "说明概念 A 的定义并给出一个例子。",
                "evidence_ids": [],
            },
            {
                "item_id": ITEM_B,
                "requirement": "REQUIRED",
                "objective": "Explain concept B",
                "acceptance": "说明概念 B 的定义并给出一个例子。",
                "evidence_ids": [],
            },
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,"
            "major,kind,status) VALUES(?,'cs3481',NULL,'覆盖验收节点',"
            "'Synthetic zero-coverage node','CS','ATOMIC','PUBLISHED')",
            (NODE,),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (NODE, content, hashlib.sha256(content.encode()).hexdigest()),
        )
        # Five validated questions with rubric criteria on ITEM_A so a real
        # assessment can be graded against this node (same shape as
        # scripts/prepare_v3_e2e.seed_assessment_fixture).
        for ordinal in range(1, 6):
            question_id = f"cov-question-{ordinal}"
            prompt = f"Synthetic coverage question {ordinal}: type correct."
            answer = {"accepted": ["correct"], "case_sensitive": False}
            question_content = json.dumps({"prompt": prompt, "answer": answer}, sort_keys=True)
            connection.execute(
                "INSERT INTO assessment_question_revisions("
                "id,course_id,owner_user_id,family_id,revision,source_kind,"
                "question_type,difficulty,prompt_text,options_json,answer_json,"
                "validation_status,verification_method,content_hash,created_by_user_id) "
                "VALUES(?,'cs3481',NULL,?,1,'OFFICIAL','SHORT_TEXT',?,?,'[]',?,"
                "'VALIDATED','OFFICIAL',?,?)",
                (
                    question_id,
                    f"cov-family-{ordinal}",
                    ordinal,
                    prompt,
                    json.dumps(answer),
                    hashlib.sha256(question_content.encode()).hexdigest(),
                    "E2E_FIXTURE_ADMIN",
                ),
            )
            connection.execute(
                "INSERT INTO assessment_rubric_criteria("
                "question_revision_id,criterion_id,node_id,spec_version,item_id,"
                "dimension,max_fraction,description,deterministic_rule_json) "
                "VALUES(?,'correctness',?,1,?,'CONCEPT',100,"
                "'Matches the synthetic fixture answer.','{}')",
                (question_id, NODE, ITEM_A),
            )


def wait_terminal(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def wait_receipt(client: TestClient, run_id: str, timeout: float = 20.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
        receipt = row.get("coverage")
        if receipt is not None:
            return receipt
        # Terminal runs that never attempted bookkeeping have no receipt row.
        if row["status"] in {"completed", "failed", "cancelled"}:
            time.sleep(0.5)
            final = client.get(f"{UI}/runs/{run_id}", headers=auth("Bearer token-a")).json()
            return final.get("coverage")
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} has no coverage receipt after {timeout}s")


def teach(client: TestClient, text: str, request_id: str, node: str = NODE) -> dict:
    conversation = client.post(
        f"{UI}/conversations",
        headers=auth("Bearer token-a"),
        json={"course": "cs3481", "lane": "teach"},
    )
    assert conversation.status_code == 201, conversation.text
    started = client.post(
        f"{UI}/conversations/{conversation.json()['id']}/runs",
        headers=auth("Bearer token-a"),
        json={"text": text, "request_id": request_id, "node_id": node},
    )
    assert started.status_code == 202, started.text
    row = wait_terminal(client, started.json()["id"])
    receipt = wait_receipt(client, started.json()["id"])
    return {"run_id": started.json()["id"], "run": row, "receipt": receipt}


def knowledge_node(client: TestClient) -> dict:
    body = client.get(f"{UI}/courses/cs3481/knowledge", headers=auth("Bearer token-a")).json()
    return next(row for row in body if row["id"] == NODE)


def evidence_rows(client: TestClient) -> list[dict]:
    with client.app.state.database.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM teaching_delivery_evidence WHERE node_id=? ORDER BY created_at",
                (NODE,),
            )
        ]


def run_async(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("run_async must be called outside a running event loop")


def test_zero_to_learning_to_learned_and_assessment_independent(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.extend(
        [
            "这是第一段讲解。说明概念 A 的定义并给出一个例子。具体来说，概念 A 是……",
            "这是第二段讲解。说明概念 B 的定义并给出一个例子。例如，概念 B 在……",
        ]
    )

    # Zero coverage before any teaching.
    assert knowledge_node(client)["progress"] == "NOT_STARTED"

    first = teach(client, "请讲解概念 A", "cov-000001")
    assert first["run"]["status"] == "completed"
    assert first["receipt"]["status"] == "submitted"
    assert json.loads(first["receipt"]["covered_items"]) == [ITEM_A]
    node = knowledge_node(client)
    assert node["progress"] == "LEARNING", node
    assert node["learning"]["required_total"] == 2
    assert node["learning"]["covered_required"] == 1
    rows = evidence_rows(client)
    assert len(rows) == 1
    assert rows[0]["validation_status"] == "REVIEWED"
    assert rows[0]["plan_version_id"] is None
    with client.app.state.database.connect() as connection:
        journey = connection.execute(
            "SELECT status FROM learning_journeys WHERE node_id=?", (NODE,)
        ).fetchone()
        assert journey["status"] == "LEARNING"
        coverage = connection.execute(
            "SELECT COUNT(*) FROM learning_coverage WHERE item_id=?", (ITEM_A,)
        ).fetchone()[0]
        assert coverage == 1

    second = teach(client, "请讲解概念 B", "cov-000002")
    assert json.loads(second["receipt"]["covered_items"]) == [ITEM_B]
    node = knowledge_node(client)
    assert node["progress"] == "LEARNED", node
    assert node["learning"]["covered_required"] == 2
    assert len(evidence_rows(client)) == 2
    with client.app.state.database.connect() as connection:
        journey = connection.execute(
            "SELECT status FROM learning_journeys WHERE node_id=?", (NODE,)
        ).fetchone()
        assert journey["status"] == "LEARNED"

    # Assessment stays independent: a low grade cannot remove LEARNED.
    started = client.post(
        f"{UI}/courses/cs3481/knowledge/{NODE}/assessment/session",
        headers=auth("Bearer token-a"),
        json={"request_id": "cov-assessment-000001"},
    )
    assert started.status_code == 201, started.text
    view = client.get(
        f"{UI}/courses/cs3481/knowledge/assessment/{started.json()['id']}",
        headers=auth("Bearer token-a"),
    ).json()
    answers = [
        {"blueprint_item_id": question["id"], "answer": "wrong"}
        for question in view["questions"]
    ]
    graded = client.post(
        f"{UI}/courses/cs3481/knowledge/assessment/{started.json()['id']}/submit",
        headers=auth("Bearer token-a"),
        json={"request_id": "cov-assessment-submit-000001", "answers": answers},
    )
    assert graded.status_code == 200, graded.text
    node = knowledge_node(client)
    assert node["progress"] == "LEARNED"
    assert node["assessment"]["status"] == "GRADED"


def test_keyword_only_content_does_not_cover(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append("概念 A 和概念 B 都很重要，都有定义和例子。")
    result = teach(client, "请讲讲这些概念", "cov-keyword-000001")
    assert result["receipt"]["status"] == "submitted"
    assert json.loads(result["receipt"]["covered_items"]) == []
    assert knowledge_node(client)["progress"] == "NOT_STARTED"
    assert evidence_rows(client) == []


def test_failed_and_truncated_runs_never_cover(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider

    provider.responses.append(RuntimeError("provider exploded"))
    failed = teach(client, "失败的教学", "cov-fail-000001")
    assert failed["run"]["status"] == "failed"
    # Failed runs never attempt bookkeeping: no receipt row, no evidence.
    assert failed["receipt"] is None
    assert evidence_rows(client) == []

    from app.cm_update.provider import ProviderError

    original = provider.generate

    async def truncated(course, text, profile, sources, history, lane, bridge=None, **kwargs):
        provider.calls.append({"lane": lane, "text": text})
        yield {"kind": "status", "status": "generating", "label": "测试模型"}
        yield {"kind": "delta", "text": "部分内容"}
        raise ProviderError("INCOMPLETE_PROVIDER_RESPONSE")

    provider.generate = truncated
    try:
        conversation = client.post(
            f"{UI}/conversations",
            headers=auth("Bearer token-a"),
            json={"course": "cs3481", "lane": "teach"},
        ).json()
        started = client.post(
            f"{UI}/conversations/{conversation['id']}/runs",
            headers=auth("Bearer token-a"),
            json={"text": "截断的教学", "request_id": "cov-trunc-000001", "node_id": NODE},
        )
        row = wait_terminal(client, started.json()["id"])
        assert row["status"] == "failed"
        assert row.get("coverage") is None
    finally:
        provider.generate = original
    assert evidence_rows(client) == []
    assert knowledge_node(client)["progress"] == "NOT_STARTED"


def test_cancel_never_books_coverage(client: TestClient) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    original = provider.generate

    async def blocked(course, text, profile, sources, history, lane, bridge=None, **kwargs):
        provider.calls.append({"lane": lane, "text": text})
        for _ in range(400):
            yield {"kind": "status", "status": "generating", "label": "阻塞中"}
            await asyncio.sleep(0.05)

    provider.generate = blocked
    try:
        conversation = client.post(
            f"{UI}/conversations",
            headers=auth("Bearer token-a"),
            json={"course": "cs3481", "lane": "teach"},
        ).json()
        started = client.post(
            f"{UI}/conversations/{conversation['id']}/runs",
            headers=auth("Bearer token-a"),
            json={"text": "会被取消的教学", "request_id": "cov-cancel-000001", "node_id": NODE},
        )
        time.sleep(0.4)
        cancelled = client.post(
            f"{UI}/runs/{started.json()['id']}/cancel", headers=auth("Bearer token-a")
        )
        assert cancelled.status_code == 200
        row = wait_terminal(client, started.json()["id"])
        assert row["status"] == "cancelled"
        assert row.get("coverage") is None
    finally:
        provider.generate = original
    assert evidence_rows(client) == []
    assert knowledge_node(client)["progress"] == "NOT_STARTED"


def test_cancel_effective_during_provider_silence(client: TestClient) -> None:
    """A provider that emits no events must not suspend cancellation: the
    database watchdog stops the run within a bounded interval (§5)."""

    provider: ScriptedProvider = client.app.state.ui_provider
    original = provider.generate

    async def silent(course, text, profile, sources, history, lane, bridge=None, **kwargs):
        provider.calls.append({"lane": lane, "text": text})
        # Yield nothing; only an external cancel can stop this generator.
        await asyncio.Event().wait()
        yield {"kind": "delta", "text": "unreachable: the gate is never released"}

    provider.generate = silent
    try:
        conversation = client.post(
            f"{UI}/conversations",
            headers=auth("Bearer token-a"),
            json={"course": "cs3481", "lane": "teach"},
        ).json()
        started = client.post(
            f"{UI}/conversations/{conversation['id']}/runs",
            headers=auth("Bearer token-a"),
            json={"text": "静默的教学", "request_id": "cov-silent-000001", "node_id": NODE},
        )
        time.sleep(0.5)
        client.post(
            f"{UI}/runs/{started.json()['id']}/cancel", headers=auth("Bearer token-a")
        )
        begin = time.monotonic()
        row = wait_terminal(client, started.json()["id"])
        elapsed = time.monotonic() - begin
        assert row["status"] == "cancelled"
        # The watchdog polls every 2s, so cancellation lands well before any
        # "forever" bound; 8s allows slow CI without hiding a hang.
        assert elapsed < 8.0, f"cancel took {elapsed:.1f}s during provider silence"
        assert row.get("coverage") is None
    finally:
        provider.generate = original
    assert evidence_rows(client) == []


def test_replay_does_not_duplicate_and_recovery_never_calls_provider(
    client: TestClient, tmp_path: Path
) -> None:
    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append("说明概念 A 的定义并给出一个例子。")
    first = teach(client, "请讲解概念 A", "cov-replay-000001")
    assert json.loads(first["receipt"]["covered_items"]) == [ITEM_A]

    # Direct replay of the same operation (what recovery does): no new rows.
    adapter = client.app.state.ui_extension_adapter
    result = run_async(
        adapter.call(
            "knowledge.submit_delivery",
            "user-a",
            {
                "course": "cs3481",
                "node": NODE,
                "spec_version": 1,
                "run_id": first["run_id"],
                "content": "说明概念 A 的定义并给出一个例子。",
            },
            "",
        )
    )
    assert result["replayed"] is True
    assert len(evidence_rows(client)) == 1
    calls_before = len(provider.calls)

    # Simulate the process dying between the V3 write and the receipt write,
    # then a fresh application instance on the same databases performs the
    # startup recovery: bookkeeping only, zero provider calls.
    ui_db = client.app.state.ui_extension_app.state.db
    ui_db.execute("DELETE FROM cmui_delivery_submissions WHERE run=?", (first["run_id"],))

    provider2 = ScriptedProvider([])
    application2 = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
        ui_provider=provider2,
        ui_coverage_reviewer=DeterministicCoverageReviewer(),
    )
    with TestClient(application2) as client2:
        receipt = client2.get(
            f"{UI}/runs/{first['run_id']}", headers=auth("Bearer token-a")
        ).json()["coverage"]
        assert receipt["status"] == "submitted"
        assert json.loads(receipt["covered_items"]) == [ITEM_A]
    assert len(provider2.calls) == 0
    assert len(evidence_rows(client)) == 1
    assert len(provider.calls) == calls_before


def test_wrong_user_course_and_stale_spec_never_cover(client: TestClient) -> None:
    adapter = client.app.state.ui_extension_adapter

    with pytest.raises(HTTPException) as wrong_course:
        run_async(
            adapter.call(
                "knowledge.submit_delivery",
                "user-a",
                {
                    "course": "cs3482",
                    "node": NODE,
                    "spec_version": 1,
                    "run_id": "cov-x-000001",
                    "content": "说明概念 A 的定义并给出一个例子。",
                },
                "",
            )
        )
    assert wrong_course.value.status_code == 404

    with pytest.raises(HTTPException) as stale_spec:
        run_async(
            adapter.call(
                "knowledge.submit_delivery",
                "user-a",
                {
                    "course": "cs3481",
                    "node": NODE,
                    "spec_version": 99,
                    "run_id": "cov-x-000002",
                    "content": "说明概念 A 的定义并给出一个例子。",
                },
                "",
            )
        )
    assert stale_spec.value.status_code == 422
    assert "spec changed" in str(stale_spec.value.detail)

    # Another user can teach the same public node, but their submission lands
    # in THEIR OWN journey; the owner's coverage must stay untouched.
    other = run_async(
        adapter.call(
            "knowledge.submit_delivery",
            "user-b",
            {
                "course": "cs3481",
                "node": NODE,
                "spec_version": 1,
                "run_id": "cov-x-000003",
                "content": "说明概念 A 的定义并给出一个例子。",
            },
            "",
        )
    )
    assert other["workspace_id"] is not None
    assert knowledge_node(client)["progress"] == "NOT_STARTED"
    # Journey-scoped check: the owner's journey gained nothing, while the
    # other user's own journey holds their reviewed evidence.
    with client.app.state.database.connect() as connection:
        owner_evidence = connection.execute(
            "SELECT e.id FROM teaching_delivery_evidence e "
            "JOIN learning_journeys j ON j.id=e.journey_id "
            "JOIN learning_workspaces w ON w.id=j.workspace_id "
            "WHERE e.node_id=? AND w.owner_user_id='user-a'",
            (NODE,),
        ).fetchall()
        other_evidence = connection.execute(
            "SELECT e.id FROM teaching_delivery_evidence e "
            "JOIN learning_journeys j ON j.id=e.journey_id "
            "JOIN learning_workspaces w ON w.id=j.workspace_id "
            "WHERE e.node_id=? AND w.owner_user_id='user-b'",
            (NODE,),
        ).fetchall()
    assert owner_evidence == []
    assert len(other_evidence) == 1


def test_old_entry_counts_reviewed_coverage(client: TestClient) -> None:
    """The query the plan-based teach() uses must see REVIEWED evidence."""

    provider: ScriptedProvider = client.app.state.ui_provider
    provider.responses.append("说明概念 A 的定义并给出一个例子。")
    teach(client, "请讲解概念 A", "cov-oldentry-000001")
    with client.app.state.database.connect() as connection:
        journey = connection.execute(
            "SELECT id FROM learning_journeys WHERE node_id=?", (NODE,)
        ).fetchone()
        covered = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT item_id FROM teaching_delivery_evidence "
                "WHERE journey_id=? AND validation_status IN "
                "('VALIDATED','LEGACY_PRESERVED','REVIEWED')",
                (journey["id"],),
            )
        }
    assert covered == {ITEM_A}
