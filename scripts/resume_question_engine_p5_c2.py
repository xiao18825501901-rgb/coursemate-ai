"""Resume the one P5 C2 run whose paid response completed before local validation.

This is not a general retry command.  It accepts only the frozen FAILED_SAFE
shape produced by ``run_question_engine_p5_live.py`` after a completed
PRACTICE_FEEDBACK response was durably recorded and then rejected locally.  The
completed body is revalidated and projected through the real practice runtime
without another provider request.  Every later network call remains bounded by
the original eight-DeepSeek/four-Jev plan and has zero SDK retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(RAG_SERVICE))

import run_question_engine_p5_live as base
from app.learning.practice_feedback import PracticeFeedbackOutput, PracticeProviderRun
from app.learning.practice_recovery import (
    inspect_practice_operations,
    reconcile_practice_operation,
)

SOURCE_ERROR = "C2_ASSISTED_ATTEMPT_HTTP_409"
SOURCE_OPERATION = "p5-attempt-assisted-0001"
RECOVERY_OPERATION = "p5-attempt-assisted-recovery-0002"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--deepseek-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--jev-key-env", default="TYPESAFE_API_KEY")
    parser.add_argument("--max-output-tokens", type=int, default=4_000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--input-price-per-million", type=float, required=True)
    parser.add_argument("--output-price-per-million", type=float, required=True)
    parser.add_argument("--operation-usd-baseline", type=float, required=True)
    parser.add_argument("--allow-billable", action="store_true")
    return parser.parse_args(argv)


def _load_recovery_evidence(run_dir: Path) -> dict[str, Any]:
    state_path = run_dir / "run-state.json"
    checkpoint_path = run_dir / "first-ready-checkpoint.json"
    ledger_path = run_dir / "private-transport-ledger.json"
    current_state_bytes = state_path.read_bytes()
    current_state = json.loads(current_state_bytes)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    ledger_payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    resuming_after_pre_network_stop = False
    if current_state.get("status") == "FAILED_SAFE":
        state_bytes = current_state_bytes
        state = current_state
    elif (
        current_state.get("status") == "RECOVERY_FAILED_SAFE"
        and current_state.get("recovery_error_code")
        == "P5_C2_RECOVERY_SOURCE_CLASSIFICATION_MISMATCH"
        and current_state.get("recovery_new_network_calls") == 0
        and current_state.get("deepseek_calls") == 5
        and current_state.get("jev_calls") == 2
        and current_state.get("transport_ledger", {}).get("event_count")
        == len(ledger_payload.get("events") or [])
    ):
        snapshot_path = run_dir / "failed-safe-state-before-c2-recovery.json"
        state_bytes = snapshot_path.read_bytes()
        state = json.loads(state_bytes)
        resuming_after_pre_network_stop = True
    else:
        raise ValueError(
            "The run is not the expected stopped C2 contract-validation state."
        )
    if state.get("status") != "FAILED_SAFE" or state.get("error_code") != SOURCE_ERROR:
        raise ValueError("The frozen source state is not the original C2 failure.")
    if checkpoint.get("status") != "FIRST_READY_QUESTION_SAVED":
        raise ValueError("The immutable first READY checkpoint is missing.")
    audit = state.get("call_budget_audit")
    if not isinstance(audit, dict):
        raise TypeError("The stopped run has no call-budget audit.")
    deepseek_roles = audit.get("deepseek_attempted_roles")
    jev_definitions = audit.get("jev_attempted_definitions")
    if not isinstance(deepseek_roles, list) or len(deepseek_roles) != 5:
        raise ValueError(
            "Recovery requires exactly five already-attempted DeepSeek calls."
        )
    if not isinstance(jev_definitions, list) or len(jev_definitions) != 2:
        raise ValueError("Recovery requires exactly two already-attempted Jev calls.")
    events = ledger_payload.get("events")
    if not isinstance(events, list):
        raise TypeError("The stopped run has no durable transport events.")
    completes = [
        event
        for event in events
        if event.get("source") == "deepseek"
        and event.get("phase") == "RESPONSE_COMPLETE"
        and event.get("role") == "PRACTICE_FEEDBACK"
    ]
    rejected = [
        event
        for event in events
        if event.get("source") == "deepseek"
        and event.get("phase") == "CONTRACT_REJECTED"
        and event.get("role") == "PRACTICE_FEEDBACK"
    ]
    if len(completes) != 2 or len(rejected) != 1:
        raise ValueError(
            "The completed/rejected practice-response sequence is not exact."
        )
    response_event = completes[-1]
    reject_event = rejected[0]
    if (
        response_event.get("input_hash") != reject_event.get("input_hash")
        or response_event.get("provider_response_id")
        != reject_event.get("provider_response_id")
        or reject_event.get("reason") != "ValidationError"
    ):
        raise ValueError("The rejected event is not bound to the completed response.")
    output = PracticeFeedbackOutput.model_validate_json(
        str(response_event["output_text"])
    )
    started_event = next(
        (
            event
            for event in reversed(events[: events.index(response_event)])
            if event.get("source") == "deepseek"
            and event.get("phase") == "SEND_INTENT"
            and event.get("role") == "PRACTICE_FEEDBACK"
            and event.get("input_hash") == response_event.get("input_hash")
        ),
        None,
    )
    if started_event is None:
        raise ValueError("The completed response has no preceding send intent.")
    started_at = str(started_event["recorded_at"])
    finished_at = str(response_event["recorded_at"])
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    run = PracticeProviderRun.model_validate(
        {
            "model": str(response_event["model"]),
            "provider": str(response_event["provider"]),
            "protocol": str(response_event["protocol"]),
            "region": "ENDPOINT_DEEPSEEK",
            "role": "PRACTICE_FEEDBACK",
            "template_version": "practice-feedback.v1",
            "schema_version": "practice-feedback-output.v1",
            "input_hash": str(response_event["input_hash"]),
            "started_at": started_at,
            "finished_at": finished_at,
            "latency_ms": max(0, int((finished - started).total_seconds() * 1000)),
            "input_tokens": int(response_event["input_tokens"]),
            "output_tokens": int(response_event["output_tokens"]),
            "provider_response_id": str(response_event["provider_response_id"]),
            "status": "COMPLETED",
            "error_class": None,
        }
    )
    return {
        "state": state,
        "state_bytes": state_bytes,
        "checkpoint": checkpoint,
        "ledger_path": ledger_path,
        "ledger_bytes": ledger_path.read_bytes(),
        "output": output,
        "provider_run": run,
        "deepseek_roles": [str(item) for item in deepseek_roles],
        "jev_definitions": [str(item) for item in jev_definitions],
        "resuming_after_pre_network_stop": resuming_after_pre_network_stop,
    }


def _ledger_usage(
    ledger: base.DurableTransportLedger,
    *,
    input_price: float,
    output_price: float,
) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    complete_calls = 0
    for event in ledger.events:
        if event.get("phase") != "RESPONSE_COMPLETE":
            continue
        if event.get("source") == "deepseek":
            input_tokens += int(event.get("input_tokens") or 0)
            output_tokens += int(event.get("output_tokens") or 0)
            complete_calls += 1
        elif event.get("source") == "deepseek-ui":
            usage = event.get("usage")
            if not isinstance(usage, list):
                continue
            input_tokens += sum(int(item.get("input_tokens") or 0) for item in usage)
            output_tokens += sum(int(item.get("output_tokens") or 0) for item in usage)
            complete_calls += 1
    return {
        "complete_deepseek_calls": complete_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimated_at_owner_prices": (
            input_tokens * input_price + output_tokens * output_price
        )
        / 1_000_000,
        "cost_basis": "ESTIMATED_FROM_DURABLE_TRANSPORT_USAGE_AT_OWNER_PRICES",
    }


def _resume(args: argparse.Namespace, evidence: dict[str, Any]) -> int:
    from app.config import Settings
    from app.main import create_app
    from fastapi import Request
    from fastapi.testclient import TestClient

    run_dir = args.run_dir.resolve()
    state_path = run_dir / "run-state.json"
    snapshot_path = run_dir / "failed-safe-state-before-c2-recovery.json"
    if snapshot_path.exists():
        if snapshot_path.read_bytes() != evidence["state_bytes"]:
            raise RuntimeError("P5_C2_RECOVERY_SOURCE_SNAPSHOT_CHANGED")
    else:
        snapshot_path.write_bytes(evidence["state_bytes"])
    snapshot_sha = hashlib.sha256(evidence["state_bytes"]).hexdigest()
    ledger = base.DurableTransportLedger.open_existing(evidence["ledger_path"])
    owner = "p5-synthetic-owner"
    auth_headers = {"Authorization": "Bearer p5-synthetic-token"}
    api = "/ui-extension/api/ui/v1"

    class P5AuthVerifier:
        def authenticate(self, request: Request) -> str | None:
            return (
                owner
                if request.headers.get("authorization") == auth_headers["Authorization"]
                else None
            )

    class FixedEmbeddingProvider:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    deepseek_key = os.environ[args.deepseek_key_env]
    jev_key = os.environ[args.jev_key_env]
    base._configure_process_environment(
        SimpleNamespace(
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
            max_output_tokens=args.max_output_tokens,
            operation_usd_baseline=args.operation_usd_baseline,
            input_price_per_million=args.input_price_per_million,
            output_price_per_million=args.output_price_per_million,
        ),
        run_dir=run_dir,
        deepseek_key=deepseek_key,
        jev_key=jev_key,
        conservative_ceiling=base.conservative_cost_ceiling(
            base.C1_C2_PLAN,
            input_price_per_million=args.input_price_per_million,
            output_price_per_million=args.output_price_per_million,
        ),
    )
    modes = ",".join(
        f"{key}={value}"
        for key, value in (
            base.REQUIRED_JEV_MODES | base.NON_REQUIRED_JEV_MODES_OFF
        ).items()
    )
    settings = Settings(
        _env_file=None,
        database_path=run_dir / "rag.sqlite3",
        upload_dir=run_dir / "uploads",
        app_env="development",
        web_origin="http://localhost:5173",
        rag_provider_mode="openai",
        v3_enabled=True,
        ui_extension_enabled=True,
        ui_web_dir=run_dir / "no-web-build",
        v3_model="deepseek-flash",
        v3_model_api_key=deepseek_key,
        v3_model_base_url=args.base_url,
        v3_max_output_tokens=args.max_output_tokens,
        v3_model_timeout_seconds=args.timeout,
        v3_daily_model_calls_per_user=20,
        v3_daily_model_calls_per_user_course=20,
        jev_definition_modes=modes,
    )
    budget = base.CallBudget(
        deepseek_limit=base.C1_C2_PLAN.deepseek_calls,
        jev_limit=base.C1_C2_PLAN.jev_calls,
        deepseek_roles=list(evidence["deepseek_roles"]),
        jev_definitions=list(evidence["jev_definitions"]),
    )
    state = dict(evidence["state"])
    state.update(
        status="C2_RECOVERY_RUNNING",
        recovery_application_sha=base._git_head(),
        recovery_source_state_sha256=snapshot_sha,
        recovery_operation_id=RECOVERY_OPERATION,
        recovery_reused_completed_response=True,
        recovery_new_network_calls=0,
    )
    base._write_json(state_path, state)
    try:
        application = create_app(
            settings=settings,
            embedding_provider=FixedEmbeddingProvider(),
            auth_verifier=P5AuthVerifier(),
        )
        learning = application.state.learning
        learning.provider.transport_event_sink = lambda event: ledger.record(
            "deepseek", event
        )
        original_generate = learning.generate
        replay_used = False

        def bounded_or_recovered_generate(
            workspace_id: str,
            operation_id: str,
            schema: Any,
            **generate_kwargs: Any,
        ) -> Any:
            nonlocal replay_used
            role = str(generate_kwargs.get("role") or "UNKNOWN")
            if operation_id == RECOVERY_OPERATION:
                if replay_used or role != "PRACTICE_FEEDBACK":
                    raise RuntimeError("P5_RECOVERED_RESPONSE_SCOPE_MISMATCH")
                if schema is not PracticeFeedbackOutput:
                    raise RuntimeError("P5_RECOVERED_RESPONSE_SCHEMA_MISMATCH")
                context = generate_kwargs.get("context")
                if not isinstance(context, dict) or context.get("assistance") != "HINT":
                    raise RuntimeError("P5_RECOVERED_RESPONSE_CONTEXT_MISMATCH")
                replay_used = True
                return evidence["output"].model_dump(mode="json"), evidence[
                    "provider_run"
                ].model_dump(mode="json")
            budget.claim_deepseek(role)
            return original_generate(
                workspace_id,
                operation_id,
                schema,
                **generate_kwargs,
            )

        learning.question_engine.metered_generate = bounded_or_recovered_generate
        gateway = application.state.jev_service.gateway
        gateway.transport = base.BoundedJevTransport(gateway.transport, budget, ledger)

        ui_model = application.state.ui_extension_app.state.provider
        original_explanation = ui_model.generate_explanation

        async def bounded_explanation(*model_args: Any, **model_kwargs: Any) -> Any:
            budget.claim_deepseek("EXPLANATION")
            ledger.record(
                "deepseek-ui", {"phase": "SEND_INTENT", "role": "EXPLANATION"}
            )
            output_parts: list[str] = []
            usage: list[dict[str, Any]] = []
            try:
                async for event in original_explanation(*model_args, **model_kwargs):
                    if isinstance(event, dict) and isinstance(event.get("text"), str):
                        output_parts.append(event["text"])
                    if isinstance(event, dict) and isinstance(event.get("usage"), dict):
                        usage.append(event["usage"])
                    if isinstance(event, dict):
                        ledger.record(
                            "deepseek-ui",
                            {
                                "phase": "RESPONSE_FRAGMENT",
                                "role": "EXPLANATION",
                                "event": event,
                            },
                        )
                    yield event
            except Exception as error:
                ledger.record(
                    "deepseek-ui",
                    {
                        "phase": "RESPONSE_UNKNOWN",
                        "role": "EXPLANATION",
                        "error_class": type(error).__name__,
                    },
                )
                raise
            ledger.record(
                "deepseek-ui",
                {
                    "phase": "RESPONSE_COMPLETE",
                    "role": "EXPLANATION",
                    "output_text": "".join(output_parts),
                    "usage": usage,
                },
            )

        ui_model.generate_explanation = bounded_explanation

        database = application.state.database
        checkpoint = evidence["checkpoint"]
        question_revision_id = str(checkpoint["question_revision_id"])
        with database.connect() as connection:
            source = inspect_practice_operations(
                connection,
                operation_id=SOURCE_OPERATION,
            )
            if (
                len(source) != 1
                or source[0].classification != "UPSTREAM_COMPLETED_NO_RESULT"
            ):
                raise RuntimeError("P5_C2_RECOVERY_SOURCE_CLASSIFICATION_MISMATCH")
            reconciled = reconcile_practice_operation(
                connection,
                workspace_id=source[0].workspace_id,
                operation_id=SOURCE_OPERATION,
                expected_classification="UPSTREAM_COMPLETED_NO_RESULT",
                disposition="UPSTREAM_COMPLETED_NO_RESULT",
                operator_ref="P5-20260925-completed-contract-response",
                evidence=evidence["ledger_bytes"],
                writers_drained=True,
            )
            if reconciled.classification != "RECONCILED_UPSTREAM_COMPLETED_NO_RESULT":
                raise RuntimeError("P5_C2_RECOVERY_RECONCILIATION_FAILED")
            before_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "grade_snapshots",
                    "performance_evidence",
                    "learning_coverage",
                )
            }

        with TestClient(application) as client:
            ui_database = application.state.ui_extension_app.state.db
            exercise = ui_database.one(
                "SELECT * FROM cmui_exercises WHERE question_revision_id=?",
                (question_revision_id,),
            )
            if exercise is None:
                raise RuntimeError("P5_C2_RECOVERY_EXERCISE_MISSING")
            exercise_id = str(exercise["id"])
            course_id = str(exercise["course"])
            pair_id = str(exercise["pair"])
            node_id = str(exercise["node"])
            stored_steps = json.loads(str(exercise["answer_steps"]))
            private_texts = [str(step["text"]) for step in stored_steps]
            assisted = base._expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/attempts",
                    headers=auth_headers,
                    json={
                        "request_id": RECOVERY_OPERATION,
                        "answer": (
                            "I now count A itself plus B and C, giving three points, so A is core."
                        ),
                    },
                ),
                200,
                "C2_RECOVERED_ASSISTED_ATTEMPT",
            )
            if not replay_used:
                raise RuntimeError("P5_C2_RECOVERED_RESPONSE_NOT_USED")
            if (
                assisted.get("assistance") != "HINT"
                or assisted.get("independent") is not False
            ):
                raise RuntimeError("C2_ASSISTANCE_MARKING_INVALID")
            with database.connect() as connection:
                retry_link = connection.execute(
                    "SELECT prior_operation_id,new_operation_id FROM "
                    "practice_operation_retry_links WHERE new_operation_id=?",
                    (RECOVERY_OPERATION,),
                ).fetchone()
            if retry_link is None or tuple(retry_link) != (
                SOURCE_OPERATION,
                RECOVERY_OPERATION,
            ):
                raise RuntimeError("P5_C2_RECOVERY_LINK_MISSING")

            revealed = base._expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/reveal",
                    headers=auth_headers,
                    json={"request_id": "p5-reveal-recovery-0002"},
                ),
                200,
                "C2_REVEAL",
            )
            if revealed.get("steps") != stored_steps:
                raise RuntimeError("C2_REVEAL_MISMATCH")
            detail_start = base._expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/steps/{stored_steps[0]['step_id']}/explanation",
                    headers=auth_headers,
                    json={"request_id": "p5-detail-recovery-0002"},
                ),
                202,
                "C2_DETAIL_START",
            )
            detail_run = base._wait_terminal(
                client, str(detail_start["run"]), auth_headers, args.timeout
            )
            if detail_run.get("status") != "completed":
                raise RuntimeError("C2_DETAIL_NOT_COMPLETED")
            detail = base._expect(
                client.get(
                    f"{api}/explanations/{detail_start['id']}", headers=auth_headers
                ),
                200,
                "C2_DETAIL",
            )
            if not str(detail.get("text") or "").strip():
                raise RuntimeError("C2_DETAIL_EMPTY")
            restored = base._expect(
                client.get(f"{api}/exercises/{exercise_id}", headers=auth_headers),
                200,
                "C2_RESTORE",
            )
            if restored.get("hint_count") != 1 or not restored.get("latest_attempt"):
                raise RuntimeError("C2_RESTORE_INCOMPLETE")
            conversation = ui_database.one(
                "SELECT conversation FROM cmui_messages WHERE exercise=?",
                (exercise_id,),
            )
            history = base._expect(
                client.get(
                    f"{api}/conversations/{conversation['conversation']}",
                    headers=auth_headers,
                ),
                200,
                "C2_HISTORY",
            )
            if not any(
                item.get("exercise") == exercise_id and item.get("exercise_state")
                for item in history.get("messages", [])
            ):
                raise RuntimeError("C2_HISTORY_STATE_MISSING")

            second_start = base._expect(
                client.post(
                    f"{api}/courses/{course_id}/exercises",
                    headers=auth_headers,
                    json={
                        "pair_id": pair_id,
                        "node": node_id,
                        "request_id": "p5-question-c2-repractice-recovery-0002",
                    },
                ),
                202,
                "C2_REPRACTICE_START",
            )
            second_run = base._wait_terminal(
                client, str(second_start["id"]), auth_headers, args.timeout
            )
            if second_run.get("status") != "completed":
                raise RuntimeError("C2_REPRACTICE_NOT_COMPLETED")

        with database.connect() as connection:
            provenance = connection.execute(
                "SELECT workspace_id FROM question_engine_provenance "
                "WHERE question_revision_id=?",
                (question_revision_id,),
            ).fetchone()
            family_rows = connection.execute(
                "SELECT question.family_id FROM question_engine_provenance AS provenance "
                "JOIN assessment_question_revisions AS question "
                "ON question.id=provenance.question_revision_id "
                "WHERE provenance.workspace_id=? ORDER BY question.rowid",
                (provenance["workspace_id"],),
            ).fetchall()
            after_counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "grade_snapshots",
                    "performance_evidence",
                    "learning_coverage",
                )
            }
            model_runs = base._rows(
                connection,
                "SELECT role,model_id,provider_label,protocol,region_label,template_version,"
                "schema_version,input_hash,started_at,finished_at,latency_ms,input_tokens,"
                "output_tokens,status,error_class,provider_response_id "
                "FROM learning_model_run_evidence ORDER BY started_at,rowid",
            )
            reservations = base._rows(
                connection,
                "SELECT operation_id,role,status,input_tokens,output_tokens,finished_at "
                "FROM learning_model_call_reservations ORDER BY created_at,rowid",
            )
            receipts = base._rows(
                connection,
                "SELECT id,definition_key,mode,caller_role,course_id,workspace_id,node_id,"
                "spec_version,question_hash,input_hash,outcome,latency_ms,model_version "
                "FROM jev_decision_receipts ORDER BY created_at,rowid",
            )
            validation_rows = base._rows(
                connection,
                "SELECT question_revision_id,validation_report_json,publication_status "
                "FROM question_engine_provenance ORDER BY rowid",
            )
            rubric = base._rows(
                connection,
                "SELECT criterion_id,dimension,max_fraction,description "
                "FROM assessment_rubric_criteria WHERE question_revision_id=? "
                "ORDER BY criterion_id",
                (question_revision_id,),
            )
            independent_row = connection.execute(
                "SELECT result_json FROM practice_interaction_operations WHERE operation_id=?",
                ("p5-attempt-independent-0001",),
            ).fetchone()
            hint_row = connection.execute(
                "SELECT result_json FROM practice_interaction_operations WHERE operation_id=?",
                ("p5-hint-0001",),
            ).fetchone()
        if before_counts != after_counts:
            raise RuntimeError("C2_PRACTICE_MUTATED_FORMAL_PROGRESS")
        if len({str(row["family_id"]) for row in family_rows}) != 2:
            raise RuntimeError("C2_REPRACTICE_FAMILY_NOT_NEW")
        if len(budget.deepseek_roles) != base.C1_C2_PLAN.deepseek_calls:
            raise RuntimeError("P5_DEEPSEEK_CALL_COUNT_MISMATCH")
        if len(budget.jev_definitions) != base.C1_C2_PLAN.jev_calls:
            raise RuntimeError("P5_JEV_CALL_COUNT_MISMATCH")
        required_receipts = [
            row for row in receipts if row["definition_key"] in base.REQUIRED_JEV_MODES
        ]
        if len(required_receipts) != 4 or any(
            row["mode"] != "on" or row["outcome"] != "ok" for row in required_receipts
        ):
            raise RuntimeError("P5_REQUIRED_JEV_RECEIPT_MISMATCH")
        if any(
            text in json.dumps(restored.get("latest_hint"), ensure_ascii=False)
            for text in private_texts
        ):
            raise RuntimeError("C2_HINT_EXACT_ANSWER_LEAK")

        independent = json.loads(str(independent_row["result_json"]))
        hint = json.loads(str(hint_row["result_json"]))
        costs = _ledger_usage(
            ledger,
            input_price=args.input_price_per_million,
            output_price=args.output_price_per_million,
        )
        if costs["complete_deepseek_calls"] != base.C1_C2_PLAN.deepseek_calls:
            raise RuntimeError("P5_DURABLE_USAGE_CALL_COUNT_MISMATCH")
        private_review = {
            "classification": "PRIVATE_HUMAN_REVIEW_MATERIAL",
            "synthetic_evidence": True,
            "case_ids": ["C1", "C2"],
            "question_revision_id": question_revision_id,
            "question": str(exercise["question"]),
            "reference_steps": stored_steps,
            "rubric": rubric,
            "independent_attempt": independent,
            "hint": hint,
            "assisted_attempt": assisted,
            "detail": detail,
            "validation_reports": validation_rows,
            "recovery": {
                "source_operation_id": SOURCE_OPERATION,
                "new_operation_id": RECOVERY_OPERATION,
                "source_state_sha256": snapshot_sha,
                "reused_completed_response": True,
                "additional_provider_call_for_recovery": False,
            },
            "human_decision": {
                "status": "PENDING_OWNER_REVIEW",
                "allowed_values": ["PASS", "REVISE", "REJECT"],
                "reason": None,
            },
        }
        base._write_json(run_dir / "private-review.json", private_review)
        public_summary = {
            "format_version": "coursejesus.p5.c1-c2.public.v1",
            "status": "LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
            "application_sha": state["application_sha"],
            "recovery_application_sha": base._git_head(),
            "started_at": state["started_at"],
            "finished_at": base._now(),
            "model": args.model,
            "endpoint_identity": args.base_url,
            "cost_policy": state["cost_policy"],
            "currency": state["currency"],
            "conservative_deepseek_ceiling": state["conservative_deepseek_ceiling"],
            "actual_usage": costs,
            "deepseek_call_roles": budget.deepseek_roles,
            "jev_call_definitions": budget.jev_definitions,
            "required_jev_receipts": required_receipts,
            "model_run_evidence": model_runs,
            "model_call_reservations": reservations,
            "question_revision_ids": [
                row["question_revision_id"] for row in validation_rows
            ],
            "question_content_sha256": checkpoint["question_content_sha256"],
            "private_answer_sha256": checkpoint["private_answer_sha256"],
            "answer_hidden_before_reveal": True,
            "exact_answer_absent_from_hint": True,
            "practice_did_not_change_formal_progress": True,
            "refresh_history_restored": True,
            "different_family_repractice": True,
            "recovery": private_review["recovery"],
            "human_content_review": "PENDING",
            "transport_ledger": ledger.public_summary(),
            "prior_attempt": state.get("prior_attempt"),
            "prior_reconciliation": state.get("prior_reconciliation"),
        }
        base._write_json(run_dir / "public-summary.json", public_summary)
        state.update(
            status="LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
            finished_at=base._now(),
            public_summary=str(run_dir / "public-summary.json"),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            call_budget_audit=budget.audit_snapshot(),
            transport_ledger=ledger.public_summary(),
            recovery_new_network_calls=3,
            recovery_reused_completed_response=True,
        )
        base._write_json(state_path, state)
        print(f"P5 C2 recovery completed; private owner review is required: {run_dir}")
        return 0
    except Exception as error:  # noqa: BLE001 - terminal evidence guard
        state.update(
            status="RECOVERY_FAILED_SAFE",
            finished_at=base._now(),
            recovery_error_class=type(error).__name__,
            recovery_error_code=base._safe_error_code(error),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            call_budget_audit=budget.audit_snapshot(),
            transport_ledger=ledger.public_summary(),
        )
        base._write_json(state_path, state)
        print(f"P5 C2 recovery stopped safely: {type(error).__name__}")
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.allow_billable:
        print(
            "Refusing recovery: --allow-billable is required for the three remaining calls."
        )
        return 2
    if args.model != "deepseek-flash" or args.base_url != "https://api.deepseek.com":
        print("Refusing recovery: the frozen model endpoint identity changed.")
        return 2
    if any(
        not isinstance(value, float) or not value > 0
        for value in (
            args.input_price_per_million,
            args.output_price_per_million,
            args.operation_usd_baseline,
        )
    ):
        print("Refusing recovery: positive prices and product baseline are required.")
        return 2
    missing = [
        name
        for name in (args.deepseek_key_env, args.jev_key_env)
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        print(
            "Refusing recovery: missing protected credential variable(s): "
            + ", ".join(missing)
        )
        return 2
    try:
        evidence = _load_recovery_evidence(args.run_dir.resolve())
    except Exception as error:  # noqa: BLE001 - no network may start after a bad checkpoint
        print(f"Refusing recovery: {type(error).__name__}: {error}")
        return 2
    print("P5 C2 RECOVERY_REQUESTED")
    print(
        "Completed assisted-feedback body will be revalidated with zero provider calls."
    )
    print("Remaining network cap: DeepSeek 3; Jev 2; automatic retries 0.")
    return _resume(args, evidence)


if __name__ == "__main__":
    raise SystemExit(main())
