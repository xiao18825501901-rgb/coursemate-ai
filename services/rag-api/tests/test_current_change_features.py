"""Contract tests for the current-change feature round (pairs, teaching modes,
plan privacy, exercises/reveals, explanations, verification, shares,
classification, campus-course gate). Uses the labelled test provider: no
billable model calls, deterministic outputs, same code paths as live."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from test_assessment_runtime import seed_assessment_pool

from app.config import Settings
from app.jev.catalog import load_catalog
from app.jev.errors import JevNotConfiguredError
from app.jev.gateway import FakeTransport, JevGateway
from app.jev.models import JevAnswer, JevResult
from app.main import create_app

UI = "/ui-extension/api/ui/v1"

SUBJECTS = {
    "Bearer token-a": "user-a",
    "Bearer token-b": "user-b",
    # token-c / token-d are the actors the campus-qualification-origin tests use
    # for "never granted" and "only a simulated historical registration row".
    # They are never qualified by any helper in this suite.
    "Bearer token-c": "user-c",
    "Bearer token-d": "user-d",
    "Bearer admin-token": "user-admin",
}


class FakeAuthVerifier:
    def authenticate(self, request: Request) -> str | None:
        return SUBJECTS.get(request.headers.get("authorization", ""))


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


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
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    # No test-only auto-verify either: registration grants nothing, so the
    # campus-content tests must qualify their actors explicitly
    # (see qualify_for_campus above) instead of leaning on a removed auto-grant.
    monkeypatch.setenv("CMUI_AUTO_VERIFY_NEW_USERS", "false")
    # The Question Engine requires two acted-on, durable semantic receipts.
    # This is an explicit offline fake transport, not a default application
    # behavior and not live TypeSafe evidence.
    def responder(call):
        key = next(iter(call.questions))
        verdict = {
            "exercise.prototype.v1": "worked_application",
            "question.ambiguity.v1": "CLEAR",
            "question.answer_agreement.v1": "AGREE",
        }.get(key)
        if verdict is None:
            return JevNotConfiguredError("not configured in this focused fixture")
        return JevResult(answers={key: JevAnswer(choice=verdict)})

    def fake_gateway(*, receipt_store, modes):
        del modes
        return JevGateway(
            transport=FakeTransport(responder),
            catalog=load_catalog(),
            modes={
                "exercise.prototype.v1": "on",
                "question.ambiguity.v1": "on",
                "question.answer_agreement.v1": "on",
            },
            receipt_store=receipt_store,
        )

    monkeypatch.setattr("app.main.JevGateway", fake_gateway)
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {user}"}


def disable_local_identity(client: TestClient, owner: str) -> None:
    """Model an approved directory tombstone without calling Clerk."""
    from app.cm_update.directory import project_local_ids
    db = client.app.state.ui_extension_app.state.db
    project_local_ids(db)
    db.execute('UPDATE cmui_directory SET active=0 WHERE subject=?', (owner,))


def wait_terminal(client: TestClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/runs/{run_id}", headers=auth("token-a")).json()
        if row["status"] in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def qualify_for_campus(client: TestClient, *subjects: str) -> None:
    """Grant campus qualification EXPLICITLY to named synthetic actors.

    Production used to grant `method='registered'` automatically on the first
    authenticated request, and the campus suites of this round relied on that to
    reach a campus course's content. That auto-grant is gone: it ran inside the
    access check itself, so the gate certified the very row it then accepted, and
    it erased the difference between a real verification and a registration.

    A test that needs campus content must therefore say so out loud here. This is
    the same explicit operator grant `tests/campus_actor_fixture.py` uses for the
    isolated integrated-host suites — not a re-introduction of the auto-grant: it
    is written in the test, it names the actor, and it never runs inside an access
    check. `user-c` is deliberately never granted, so the tests that pin "a new
    registration is unqualified" have an actor to use.
    """
    from app.cm_update.social import set_verified
    db = client.app.state.ui_extension_app.state.db
    for subject in subjects:
        set_verified(db, subject, 'admin', 'explicit test qualification, auto-grant removed')


def make_course(client: TestClient) -> None:
    created = client.post(
        "/api/courses",
        headers=auth("admin-token"),
        json={"id": "cs3481", "name": "Fundamentals of Data Science", "description": "Notes"},
    )
    assert created.status_code == 201, created.text
    # ensure the two student users exist in the UI user table
    for token in ("token-a", "token-b"):
        client.get(f"{UI}/me", headers=auth(token))
    # cs3481 is an official (campus) course, so every campus-content test in this
    # round needs real qualification. Registration no longer grants it, so the two
    # declared synthetic actors are qualified explicitly; tests that exercise a
    # deleted/disabled identity still create a local tombstone, which dominates
    # this grant. `user-c` is intentionally left unqualified.
    qualify_for_campus(client, "user-a", "user-b")
    # Binding contracts require real authorized nodes rather than invented IDs.
    # Question evidence/specs are opt-in via prepare_exercise_course so unrelated
    # tree/snapshot tests retain their original SPEC_UNAVAILABLE baseline.
    with client.app.state.database.connect() as db:
        for node in ('node-x','node-y'):
            db.execute("INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) VALUES(?,'cs3481','user-a',?,'Synthetic definition','CS','ATOMIC','PRIVATE')",(node,node))


def prepare_exercise_course(client: TestClient, node_id: str = "node-x") -> None:
    """Create the shared course plus one objective-scoped, physical evidence file."""

    make_course(client)
    seed_question_objective(client, node_id, node_id.replace("-", " "))


def _seed_question_evidence(client: TestClient) -> None:
    evidence = "A core point has at least MinPts points in its epsilon neighbourhood."
    fixture_path = Path(client.app.state.settings.upload_dir) / "question-fixture.md"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(evidence, encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.encode()).hexdigest()
    with client.app.state.database.connect() as db:
        if db.execute(
            "SELECT 1 FROM documents WHERE id='doc-question-fixture'"
        ).fetchone():
            return
        # The API correctly creates this official course in its published state,
        # where production triggers freeze the corpus.  This focused synthetic
        # fixture must nevertheless install its deterministic evidence without
        # weakening those application safeguards.  Save and restore the exact
        # database-owned trigger definitions inside this one test transaction.
        trigger_names = (
            "lock_course_document_insert_during_publication",
            "lock_course_chunk_insert_during_publication",
        )
        placeholders = ",".join("?" for _ in trigger_names)
        trigger_rows = db.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type='trigger' "
            f"AND name IN ({placeholders})",
            trigger_names,
        ).fetchall()
        assert {row["name"] for row in trigger_rows} == set(trigger_names)
        for row in trigger_rows:
            db.execute(f'DROP TRIGGER IF EXISTS "{row["name"]}"')
        try:
            db.execute(
                "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,"
                "sha256,byte_size,status,chunk_count) VALUES('doc-question-fixture','cs3481',"
                "'question-fixture.md',?,'text/markdown','.md',?,?,'ready',1)",
                (str(fixture_path.resolve()), evidence_sha, len(evidence.encode())),
            )
            db.execute(
                "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,"
                "locator_value,section,embedding) VALUES('chunk-question-fixture',"
                "'doc-question-fixture','cs3481',0,?,'page','1','DBSCAN','[]')",
                (evidence,),
            )
        finally:
            for row in trigger_rows:
                db.execute(row["sql"])


def seed_question_objective(client: TestClient, node_id: str, title: str) -> None:
    """Give an existing synthetic node one real REQUIRED objective/evidence bind."""

    _seed_question_evidence(client)
    item = {
        "item_id": f"objective-{node_id}",
        "requirement": "REQUIRED",
        "objective": f"解释 {title} 并应用课程规则判断结果",
        "acceptance": "结论和步骤均由已绑定课程规则支持",
        "evidence_ids": ["chunk-question-fixture"],
    }
    content = json.dumps([item], ensure_ascii=False, sort_keys=True)
    with client.app.state.database.connect() as db:
        db.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) "
            "VALUES(?,1,?,?)",
            (node_id, content, hashlib.sha256(content.encode()).hexdigest()),
        )


def collect_events(client: TestClient, run_id: str) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    with client.stream("GET", f"{UI}/runs/{run_id}/events?after=0", headers=auth("token-a")) as response:
        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                event_type, data = None, None
                for line in frame.splitlines():
                    if line.startswith("event: "):
                        event_type = line[len("event: "):]
                    elif line.startswith("data: "):
                        data = line[len("data: "):]
                if event_type and data is not None:
                    try:
                        rows.append((event_type, json.loads(data)))
                    except json.JSONDecodeError:
                        rows.append((event_type, data))
    return rows


# ---------------------------------------------------------------- templates


def test_template_registry_has_15_distinct_full_bodies() -> None:
    from app.cm_update import templates

    registry = templates.registry()
    assert len(registry) == 15
    assert len({entry["body_sha256"] for entry in registry.values()}) == 15, "templates merged into one body"
    professional = [v for k, v in registry.items() if k != "OTHER"]
    assert all(len(entry["body"]) > 5000 for entry in professional), "template bodies were truncated"
    assert len(registry["OTHER"]["body"]) > 2000
    assert registry["OTHER"]["body_sha256"] != professional[0]["body_sha256"]
    assert templates.exercise_prompt() and templates.problem_prompt() and templates.explanation_prompt()
    assert templates.plan_writer_instruction()
    other = registry["OTHER"]
    assert other["professional"].startswith("其他")


# ---------------------------------------------------------------- pairs


def test_pair_lifecycle_restores_both_lanes(client: TestClient) -> None:
    make_course(client)
    created = client.post(f"{UI}/pairs", headers=auth("token-a"), json={"course": "cs3481"})
    assert created.status_code == 201, created.text
    pair_id = created.json()["id"]
    assert created.json()["teach"] is None and created.json()["problem"] is None

    listed = client.get(f"{UI}/pairs?course_id=cs3481", headers=auth("token-a"))
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [pair_id]

    renamed = client.patch(f"{UI}/pairs/{pair_id}", headers=auth("token-a"), json={"title": "复习 DBSCAN"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "复习 DBSCAN"

    deleted = client.delete(f"{UI}/pairs/{pair_id}", headers=auth("token-a"))
    assert deleted.status_code == 200
    assert client.get(f"{UI}/pairs/{pair_id}", headers=auth("token-a")).status_code == 404


def test_a_new_registration_is_not_qualified_and_campus_content_is_refused(
    client: TestClient,
) -> None:
    """Registration grants no campus qualification any more.

    This test used to assert the opposite — that the first authenticated request
    returned `{"verified": true, "method": "registered"}` and that campus content
    then answered 200 without a code, a second login or an operator. The owner
    stopped that auto-grant: it was written by the access check itself (so the
    gate certified the row it accepted) and it made a registration
    indistinguishable from a real verification.

    `user-c` is used because no helper in this suite qualifies it: `make_course`
    qualifies `user-a`/`user-b` explicitly for the campus-content tests. Nothing
    is denied by deletion — the actor simply was never granted anything, and
    `user-a`/`user-b`'s own rows are untouched by this test.
    """
    make_course(client)
    status = client.get(f"{UI}/me/verification", headers=auth("token-c"))
    assert status.status_code == 200, status.text
    assert status.json() == {"verified": False, "method": None, "verified_at": None}
    db = client.app.state.ui_extension_app.state.db
    assert db.one('SELECT * FROM cmui_verification WHERE owner=?', ("user-c",)) is None, \
        "registration must leave no qualification row at all (verified=0, method NULL)"

    assert client.put(f"{UI}/courses/cs3481/pin", headers=auth("token-c")).status_code == 403
    assert client.get(f"{UI}/courses/cs3481/files", headers=auth("token-c")).status_code == 403


def test_disabled_local_identity_is_not_requalified_or_given_campus_content(client: TestClient) -> None:
    make_course(client)
    disable_local_identity(client, 'user-b')
    status = client.get(f"{UI}/me/verification", headers=auth("token-b"))
    assert status.status_code == 200
    assert status.json()["verified"] is False
    assert client.put(f"{UI}/courses/cs3481/pin", headers=auth("token-b")).status_code == 403
    assert client.get(f"{UI}/courses/cs3481/files", headers=auth("token-b")).status_code == 403


def test_pair_node_binding_unique_and_switchable(client: TestClient) -> None:
    make_course(client)
    pair_a = client.post(f"{UI}/pairs", headers=auth("token-a"), json={"course": "cs3481"}).json()["id"]
    pair_b = client.post(f"{UI}/pairs", headers=auth("token-a"), json={"course": "cs3481"}).json()["id"]

    bound = client.post(f"{UI}/pairs/{pair_a}/bind", headers=auth("token-a"), json={"node": "node-x"})
    assert bound.status_code == 200, bound.text
    assert bound.json()["bound_node"] == "node-x"

    conflict = client.post(f"{UI}/pairs/{pair_b}/bind", headers=auth("token-a"), json={"node": "node-x"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "NODE_ALREADY_BOUND"

    switch = client.post(f"{UI}/pairs/{pair_a}/bind", headers=auth("token-a"), json={"node": "node-y"})
    assert switch.status_code == 200
    assert switch.json()["bound_node"] == "node-y"

    unbind = client.post(f"{UI}/pairs/{pair_a}/bind", headers=auth("token-a"), json={"node": None})
    assert unbind.status_code == 200
    assert unbind.json()["bound_node"] is None


# ------------------------------------------------------- modes and plan privacy


def test_normal_mode_is_single_stage_and_thinking_runs_plan(client: TestClient) -> None:
    make_course(client)
    conv = client.post(f"{UI}/conversations", headers=auth("token-a"),
                       json={"course": "cs3481", "lane": "teach"}).json()
    normal = client.post(
        f"{UI}/conversations/{conv['id']}/runs", headers=auth("token-a"),
        json={"text": "请解释核心点", "request_id": "mode-normal-0001", "teaching_mode": "normal"},
    )
    assert normal.status_code == 202
    events_normal = collect_events(client, normal.json()["id"])
    kinds_normal = {kind for kind, _ in events_normal}
    assert "prompt_ready" not in kinds_normal, "normal mode must not run the plan stage"

    thinking = client.post(
        f"{UI}/conversations/{conv['id']}/runs", headers=auth("token-a"),
        json={"text": "继续", "request_id": "mode-thinking-0001", "teaching_mode": "thinking"},
    )
    assert thinking.status_code == 202
    events_thinking = collect_events(client, thinking.json()["id"])
    kinds_thinking = {kind for kind, _ in events_thinking}
    assert "prompt_ready" in kinds_thinking, "thinking mode must run the plan stage"
    status_labels = [data.get("label") for kind, data in events_thinking if kind == "status"]
    assert "正在思考中" in status_labels and "正在输出中" in status_labels


def test_run_response_never_exposes_plan_text(client: TestClient) -> None:
    make_course(client)
    conv = client.post(f"{UI}/conversations", headers=auth("token-a"),
                       json={"course": "cs3481", "lane": "teach"}).json()
    started = client.post(
        f"{UI}/conversations/{conv['id']}/runs", headers=auth("token-a"),
        json={"text": "请解释核心点", "request_id": "privacy-0001", "teaching_mode": "thinking"},
    ).json()
    wait_terminal(client, started["id"])
    row = client.get(f"{UI}/runs/{started['id']}", headers=auth("token-a")).json()
    assert "generated_prompt" not in row, "plan text must never leave the server"
    assert "lease_worker" not in row and "lease_heartbeat" not in row
    events = collect_events(client, started["id"])
    for kind, data in events:
        if kind == "prompt_ready":
            assert set(data.keys()) <= {"characters"}, "prompt_ready must carry only a length"
        else:
            assert "generated_prompt" not in json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------- exercises


def test_integrated_assessment_rejects_bad_payload_without_500_then_grades_five_answers(
    client: TestClient,
) -> None:
    """Exercise the same mounted UI route that produced the GE2324 production 500."""

    prepare_exercise_course(client)
    expected = seed_assessment_pool(
        client,
        {"id": "node-x"},
        prefix="integrated-submit-",
        item_id="objective-node-x",
        private_owner="user-a",
    )

    started = client.post(
        f"{UI}/courses/cs3481/knowledge/node-x/assessment/session",
        headers=auth("token-a"),
        json={"request_id": "integrated-assessment-start"},
    )
    assert started.status_code == 201, started.text
    view = started.json()
    assert view["status"] == "IN_PROGRESS"
    assert len(view["questions"]) == 5

    invalid = client.post(
        f"{UI}/courses/cs3481/knowledge/assessment/{view['id']}/submit",
        headers=auth("token-a"),
        json={
            "request_id": "integrated-assessment-invalid",
            "answers": [],
            "unified_answer": "",
            "attachments": [],
            "confirm_unanswered": [],
        },
    )
    assert invalid.status_code == 422, invalid.text
    invalid_body = invalid.json()
    assert "answer" in str(invalid_body.get("detail", "")).lower()

    submitted = client.post(
        f"{UI}/courses/cs3481/knowledge/assessment/{view['id']}/submit",
        headers=auth("token-a"),
        json={
            "request_id": "integrated-assessment-submit",
            "answers": [
                {
                    "blueprint_item_id": question["id"],
                    "answer": expected[question["question_revision_id"]],
                }
                for question in view["questions"]
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["status"] == "GRADED"
    assert result["raw_score"] == 100
    assert all(question["review"]["submitted_answer"] is not None for question in result["questions"])
    assert all(question["review"]["answer"] for question in result["questions"])


# ---------------------------------------------------------------- exercises


def test_exercise_hides_answer_until_reveal(client: TestClient) -> None:
    prepare_exercise_course(client)
    pair = client.post(f"{UI}/pairs", headers=auth("token-a"), json={"course": "cs3481"}).json()
    started = client.post(
        f"{UI}/courses/cs3481/exercises", headers=auth("token-a"),
        json={"request_id": "exercise-0001"},
    )
    assert started.status_code == 202, started.text
    wait_terminal(client, started.json()["id"])
    messages = client.get(f"{UI}/pairs/{pair['id']}", headers=auth("token-a")).json()["problem"]["messages"]
    assistant = [m for m in messages if m["role"] == "assistant" and m["exercise"]]
    assert assistant, "exercise question must land as a problem-lane assistant message"
    exercise_id = assistant[0]["exercise"]

    hidden = client.get(f"{UI}/exercises/{exercise_id}", headers=auth("token-a")).json()
    assert hidden["revealed"] is False
    assert hidden["steps"] == []
    assert "标准答案" not in hidden["question"]

    revealed = client.post(f"{UI}/exercises/{exercise_id}/reveal", headers=auth("token-a"))
    assert revealed.status_code == 200
    steps = revealed.json()["steps"]
    assert steps
    assert all(s["step_id"] and s["ordinal"] and s["title"] and s["text"] for s in steps)

    again = client.post(f"{UI}/exercises/{exercise_id}/reveal", headers=auth("token-a")).json()
    assert [s["step_id"] for s in again["steps"]] == [s["step_id"] for s in steps]


def test_explanation_flow_and_reuse(client: TestClient) -> None:
    prepare_exercise_course(client)
    pair = client.post(f"{UI}/pairs", headers=auth("token-a"), json={"course": "cs3481"}).json()
    started = client.post(
        f"{UI}/courses/cs3481/exercises", headers=auth("token-a"), json={"request_id": "exercise-x1"}
    ).json()
    wait_terminal(client, started["id"])
    messages = client.get(f"{UI}/pairs/{pair['id']}", headers=auth("token-a")).json()["problem"]["messages"]
    exercise_id = next(m["exercise"] for m in messages if m.get("exercise"))
    steps = client.post(f"{UI}/exercises/{exercise_id}/reveal", headers=auth("token-a")).json()["steps"]

    created = client.post(
        f"{UI}/exercises/{exercise_id}/steps/{steps[0]['step_id']}/explanation",
        headers=auth("token-a"), json={"request_id": "explanation-0001"},
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run"]
    wait_terminal(client, run_id)
    detail = client.get(f"{UI}/explanations/{created.json()['id']}", headers=auth("token-a")).json()
    assert detail["status"] == "completed"
    assert detail["text"]

    reuse = client.post(
        f"{UI}/exercises/{exercise_id}/steps/{steps[0]['step_id']}/explanation",
        headers=auth("token-a"), json={"request_id": "explanation-0002"},
    )
    assert reuse.status_code == 202
    assert reuse.json().get("reused") is True

    follow = client.post(
        f"{UI}/explanations/{created.json()['id']}/messages",
        headers=auth("token-a"), json={"text": "再讲细一点", "request_id": "explanation-msg-0001"},
    )
    assert follow.status_code == 202, follow.text
    wait_terminal(client, follow.json()["run"])


# --------------------------------------------------------------- verification


def test_code_redemption_is_what_qualifies_and_legacy_provenance_is_never_overwritten(client: TestClient) -> None:
    """A 7-digit code is the way in, and it is recorded as the real origin.

    The old version of this test asserted that a first authenticated request
    auto-qualified an active registration and that a later code redemption must
    not overwrite that provenance. Registration grants nothing now, so the
    redemption is what qualifies `user-c`, and `method='code'` is preserved as
    the honest origin. The "never overwrite a real provenance" half is kept
    against `user-b`, whose explicit operator grant must survive a redemption.
    """
    make_course(client)
    issued = client.post(f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 2})
    assert issued.status_code == 201
    codes = issued.json()["codes"]
    assert len(codes) == 2 and all(len(c) == 7 and c.isdigit() for c in codes)

    # An unqualified registration cannot read campus content and holds no row ...
    assert client.get(f"{UI}/courses/cs3481/files", headers=auth("token-c")).status_code == 403
    before = client.get(f"{UI}/me/verification", headers=auth("token-c")).json()
    assert before["verified"] is False and before["method"] is None

    # ... and redeeming a valid code grants it, with a provable origin.
    redeemed = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-c"),
        json={"code": codes[0], "request_id": "redeem-0001"},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["verified"] is True
    after = client.get(f"{UI}/me/verification", headers=auth("token-c")).json()
    assert after["verified"] is True and after["method"] == "code"

    # same code cannot be used by another account
    second = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-a"),
        json={"code": codes[0], "request_id": "redeem-0002"},
    )
    assert second.status_code == 400

    # idempotent for the redeemer
    again = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-c"),
        json={"code": codes[0], "request_id": "redeem-0003"},
    )
    assert again.status_code == 200

    assert client.get(f"{UI}/courses/cs3481/files", headers=auth("token-c")).status_code == 200

    # Redemption succeeds for a user who is already qualified, but the existing
    # provenance wins: the operator grant on user-b is not rewritten to 'code'.
    proven = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-b"),
        json={"code": codes[1], "request_id": "redeem-0004"},
    )
    assert proven.status_code == 200, proven.text
    assert client.get(f"{UI}/me/verification", headers=auth("token-b")).json()["method"] == "admin"


def test_grandfather_boundary_is_one_time() -> None:
    from app.cm_update.db import Database
    from app.cm_update import social

    db = Database(Path("grandfather-test.sqlite3"))
    db.initialize()
    db.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES ('old-user','老用户','old-user-handle','2026-01-01T00:00:00Z')")
    social.grandfather_existing_users(db, ["old-user"])
    assert social.verification_status(db, "old-user")["verified"] is True
    assert social.verification_status(db, "old-user")["method"] == "grandfathered"
    db.execute("INSERT INTO cmui_users(id,name,handle,created_at) VALUES ('new-user','新用户','new-user-handle','2026-02-01T00:00:00Z')")
    social.grandfather_existing_users(db, ["old-user", "new-user"])
    assert social.verification_status(db, "new-user")["verified"] is False
    db.path.unlink(missing_ok=True)
    Path("grandfather-test.sqlite3-wal").unlink(missing_ok=True)
    Path("grandfather-test.sqlite3-shm").unlink(missing_ok=True)


# ------------------------------------------------------------------ shares


def test_share_snapshot_and_join(client: TestClient) -> None:
    make_course(client)
    # sender creates a private course and uploads a file (standalone path only;
    # integrated course creation via /api/courses works for admin, so create a
    # private course through the V3 API as the student-visible owner)
    created = client.post(
        "/api/courses", headers=auth("admin-token"),
        json={"id": "private-x", "name": "My Private Course", "description": ""},
    )
    assert created.status_code == 201
    share = client.post(
        f"{UI}/shares", headers=auth("token-a"),
        json={"course": "cs3481", "recipients": ["user-b"],
              "history_scope": "none", "request_id": "share-0001"},
    )
    assert share.status_code == 201, share.text
    assert share.json()["status"] == "ready"

    received = client.get(f"{UI}/shares?q=received", headers=auth("token-b"))
    assert received.status_code == 200
    rows = [r for r in received.json() if r["id"] == share.json()["id"]]
    assert rows and rows[0]["requires_student_verification"] is True

    # Active recipients have the same automatic qualification for campus
    # snapshots; legacy code redemption is separately covered above.
    joined = client.post(f"{UI}/shares/{share.json()['id']}/join", headers=auth("token-b"))
    assert joined.status_code == 200, joined.text
    joined_course = joined.json()["joined_course_id"]

    # idempotent join
    again = client.post(f"{UI}/shares/{share.json()['id']}/join", headers=auth("token-b"))
    assert again.status_code == 200
    assert again.json()["joined_course_id"] == joined_course

    # the joined course is a shared-display course owned by the recipient
    detail = client.get(f"{UI}/courses/{joined_course}", headers=auth("token-b")).json()
    assert detail["display_type"] == "shared"


# ------------------------------------------------------------- classification


def test_classification_manual_and_auto(client: TestClient) -> None:
    make_course(client)
    manual = client.post(
        f"{UI}/courses/cs3481/classification", headers=auth("admin-token"),
        json={"template_id": "02"},
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["template_id"] == "02"
    assert manual.json()["source"] == "manual"

    # manual corrections survive an automatic attempt (auto only for source=auto)
    created = client.post(
        "/api/courses", headers=auth("admin-token"),
        json={"id": "auto-course", "name": "CS3481 Data Science", "description": ""},
    )
    assert created.status_code == 201
    upload = client.post(
        f"{UI}/courses/auto-course/files", headers=auth("token-a"),
        files={"file": ("notes.md", "# 数据科学\n统计学基础。".encode("utf-8"), "text/markdown")},
        data={"folder": ""},
    )
    assert upload.status_code in (201, 200), upload.text
    deadline = time.monotonic() + 10
    row = None
    while time.monotonic() < deadline:
        row = client.get(f"{UI}/courses/auto-course/classification", headers=auth("token-a")).json()
        if row["status"] in {"CLASSIFIED", "OTHER", "FAILED_RETRYABLE"}:
            break
        time.sleep(0.2)
    assert row is not None and row["status"] == "CLASSIFIED"
    assert row["template_id"] == "03"
