"""Bounded P5 C3/C4/C5 live acceptance runner.

The default execution is a zero-network static preflight. A billable run uses
the production Question Engine, AssessmentService, DeepSeek Responses adapter,
and Jev gateway against an isolated synthetic database. It never retries a
provider call and persists the private transport ledger before parsing output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MethodType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import Settings
from app.evaluation.deepseek_canary import (
    COST_POLICIES,
    COST_POLICY_CAPPED,
    COST_POLICY_OWNER_AUTHORIZED_UNLIMITED,
)
from app.evaluation.provider_safety import validate_deepseek_base_url
from app.jev.catalog import load_catalog
from app.learning.assessment_question_slots import default_assessment_question_slots
from app.learning.models import (
    AssessmentAnswer,
    AssessmentStartInput,
    AssessmentSubmitInput,
)
from app.learning.question_blueprint import resolve_objective
from app.learning.question_evidence import EvidencePackAccess, build_evidence_pack
from app.learning.question_runtime import _PROTOTYPES
from app.main import create_app
from run_question_engine_p5_live import (
    REQUIRED_JEV_MODES,
    BoundedJevTransport,
    CallBudget,
    DurableTransportLedger,
    _git_head,
    _now,
    _rows,
    _seed_synthetic_objective,
    _write_json,
)


@dataclass(frozen=True, slots=True)
class LivePlan:
    deepseek_calls: int = 13
    jev_calls: int = 14
    input_tokens_per_call: int = 15_000
    output_tokens_per_call: int = 4_000


PLAN = LivePlan()
OWNER = "p5-c3-c5-synthetic-owner"
COURSE = "p5-c3-c5-synthetic-course"
PREPARE_OPERATION = "p5-c5-prepare-live-0001"
START_OPERATION = "p5-c5-start-live-0001"
SUBMIT_OPERATION = "p5-c5-submit-live-0001"
RULE_OPERATION = "p5-c4-rule-live-0001"


class FixedEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class P5AuthVerifier:
    """Local isolated-run identity adapter; no production identity is accepted."""

    def authenticate(self, _request: Any) -> str:
        return OWNER


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prior-c1-c2-summary", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--deepseek-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--jev-key-env", default="TYPESAFE_API_KEY")
    parser.add_argument("--max-output-tokens", type=int, default=4_000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--operation-usd-baseline", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--max-cost", type=float)
    parser.add_argument(
        "--cost-policy", choices=list(COST_POLICIES), default=COST_POLICY_CAPPED
    )
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _ceiling(args: argparse.Namespace) -> float | None:
    if not (_positive(args.input_price_per_million) and _positive(args.output_price_per_million)):
        return None
    return PLAN.deepseek_calls * (
        PLAN.input_tokens_per_call * args.input_price_per_million
        + args.max_output_tokens * args.output_price_per_million
    ) / 1_000_000


def _actual_cost(
    run_rows: list[dict[str, Any]], *, input_price: float, output_price: float
) -> dict[str, Any]:
    input_tokens = sum(int(row.get("input_tokens") or 0) for row in run_rows)
    output_tokens = sum(int(row.get("output_tokens") or 0) for row in run_rows)
    complete = len(run_rows) == PLAN.deepseek_calls and all(
        int(row.get("input_tokens") or 0) > 0 or int(row.get("output_tokens") or 0) > 0
        for row in run_rows
    )
    return {
        "complete_deepseek_calls": len(run_rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimated_at_owner_prices": (
            (input_tokens * input_price + output_tokens * output_price) / 1_000_000
            if complete
            else None
        ),
        "cost_basis": (
            "ESTIMATED_FROM_DURABLE_RUN_USAGE_AT_OWNER_PRICES"
            if complete
            else "UNKNOWN_INCOMPLETE_USAGE"
        ),
    }


def _all_modes() -> dict[str, str]:
    modes = {key: "off" for key in load_catalog().definitions}
    modes.update(REQUIRED_JEV_MODES)
    return modes


def _modes_text() -> str:
    return ",".join(f"{key}={value}" for key, value in _all_modes().items())


def _prior_summary(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED"
        or payload.get("human_content_review") != "PENDING"
    ):
        raise ValueError("prior C1/C2 summary is not the expected pending-review result")
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "application_sha": payload.get("recovery_application_sha")
        or payload.get("application_sha"),
        "question_revision_ids": payload.get("question_revision_ids"),
        "actual_usage": payload.get("actual_usage"),
        "prior_unknown_reconciliation": payload.get("prior_reconciliation"),
    }


def _settings(
    *,
    root: Path,
    args: argparse.Namespace,
    deepseek_key: str | None,
) -> Settings:
    return Settings(
        _env_file=None,
        database_path=root / "rag.sqlite3",
        upload_dir=root / "uploads",
        app_env="development" if deepseek_key else "test",
        auth_test_user_id=None if deepseek_key else OWNER,
        web_origin="http://localhost:5173",
        rag_provider_mode="openai" if deepseek_key else "deterministic",
        v3_enabled=True,
        ui_extension_enabled=False,
        v3_model="deepseek-flash",
        v3_model_api_key=deepseek_key,
        v3_model_base_url=args.base_url,
        v3_max_output_tokens=args.max_output_tokens,
        v3_model_timeout_seconds=args.timeout,
        v3_daily_model_calls_per_user=20,
        v3_daily_model_calls_per_user_course=20,
        jev_definition_modes=_modes_text(),
    )


def _seed(application: Any, root: Path) -> tuple[str, str, str]:
    database = application.state.database
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility,publication_status) "
            "VALUES(?,?,?,'user','private','private')",
            (COURSE, "P5 C3-C5 synthetic DBSCAN acceptance", OWNER),
        )
    node_id = _seed_synthetic_objective(application, COURSE, OWNER, root)
    with database.connect() as connection:
        workspace = connection.execute(
            "SELECT id,private_course_id FROM learning_workspaces "
            "WHERE owner_user_id=? AND course_id=?",
            (OWNER, COURSE),
        ).fetchone()
    if workspace is None:
        raise RuntimeError("P5_C3_C5_WORKSPACE_MISSING")
    return str(workspace["id"]), str(workspace["private_course_id"]), node_id


def _static_blueprints(application: Any, workspace_id: str, private_course: str, node_id: str) -> dict[str, Any]:
    """Build all exact C3-C5 blueprints without claiming operations or calling a network."""

    runtime = application.state.learning.question_engine
    database = application.state.database
    with database.connect() as connection:
        before = {
            "operations": connection.execute("SELECT COUNT(*) FROM learning_operations").fetchone()[0],
            "reservations": connection.execute(
                "SELECT COUNT(*) FROM learning_model_call_reservations"
            ).fetchone()[0],
            "runs": connection.execute("SELECT COUNT(*) FROM learning_model_run_evidence").fetchone()[0],
            "receipts": connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0],
        }
        objective = resolve_objective(connection, node_id=node_id)
        pool_count = connection.execute(
            "SELECT COUNT(*) FROM question_engine_provenance WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()[0]
    evidence = build_evidence_pack(
        database,
        objective=objective,
        access=EvidencePackAccess(
            owner_user_id=OWNER,
            course_id=COURSE,
            private_course_id=private_course,
        ),
    )
    assessment = []
    for slot in default_assessment_question_slots():
        blueprint = runtime._assessment_blueprint(
            course_id=COURSE,
            objective=objective,
            evidence=evidence,
            slot=slot,
            preparation_key="p5-c5-static-preparation",
        )
        assessment.append(
            {
                "ordinal": slot.ordinal,
                "marks": slot.marks,
                "question_type": slot.question_type,
                "blueprint_hash": blueprint.identity(),
            }
        )
    rule = runtime._blueprint(
        course_id=COURSE,
        objective=objective,
        evidence=evidence,
        prototype=_PROTOTYPES["rule_violation_analysis"],
        operation_id="p5-c4-static-rule-operation",
    )
    with database.connect() as connection:
        after = {
            "operations": connection.execute("SELECT COUNT(*) FROM learning_operations").fetchone()[0],
            "reservations": connection.execute(
                "SELECT COUNT(*) FROM learning_model_call_reservations"
            ).fetchone()[0],
            "runs": connection.execute("SELECT COUNT(*) FROM learning_model_run_evidence").fetchone()[0],
            "receipts": connection.execute("SELECT COUNT(*) FROM jev_decision_receipts").fetchone()[0],
        }
    if before != after or pool_count != 0:
        raise RuntimeError("P5_C3_C5_STATIC_PREFLIGHT_MUTATED_STATE")
    return {
        "status": "STATIC_PREFLIGHT_PASSED",
        "network_calls": 0,
        "empty_eligible_question_pool": True,
        "evidence_pack_hash": evidence.identity(),
        "assessment_slots": assessment,
        "rule_blueprint_hash": rule.identity(),
        "ledger_counts_before": before,
        "ledger_counts_after": after,
    }


def _validate(args: argparse.Namespace) -> tuple[float | None, list[str]]:
    errors: list[str] = []
    try:
        args.base_url = validate_deepseek_base_url(args.base_url)
    except ValueError as error:
        errors.append(str(error))
    if args.model != "deepseek-flash":
        errors.append("Only deepseek-flash is accepted.")
    if not 500 <= args.max_output_tokens <= 8_000:
        errors.append("--max-output-tokens must be between 500 and 8000.")
    if not 30 <= args.timeout <= 600:
        errors.append("--timeout must be between 30 and 600 seconds.")
    try:
        _prior_summary(args.prior_c1_c2_summary)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"invalid --prior-c1-c2-summary: {error}")
    ceiling = _ceiling(args)
    if args.allow_billable and not args.preflight_only:
        if args.run_dir.exists():
            errors.append("Refusing to overwrite an existing run directory.")
        if ceiling is None:
            errors.append("Explicit positive input/output prices are required.")
        if not _positive(args.operation_usd_baseline):
            errors.append("--operation-usd-baseline is required and must be positive.")
        if args.cost_policy == COST_POLICY_CAPPED:
            if not _positive(args.max_cost):
                errors.append("--max-cost is required for capped policy.")
            elif ceiling is not None and ceiling > args.max_cost:
                errors.append("The conservative ceiling exceeds --max-cost.")
        elif args.cost_policy != COST_POLICY_OWNER_AUTHORIZED_UNLIMITED:
            errors.append("Unknown cost policy.")
        missing = [
            name
            for name in (args.deepseek_key_env, args.jev_key_env)
            if not os.environ.get(name)
        ]
        if missing:
            errors.append("Missing protected credential variable(s): " + ", ".join(missing))
    return ceiling, errors


def _preflight(args: argparse.Namespace, ceiling: float | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="coursejesus-p5-c3-c5-static-") as temporary:
        root = Path(temporary)
        application = create_app(
            settings=_settings(root=root, args=args, deepseek_key=None),
            embedding_provider=FixedEmbeddingProvider(),
        )
        workspace_id, private_course, node_id = _seed(application, root)
        result = _static_blueprints(
            application, workspace_id, private_course, node_id
        )
    result.update(
        {
            "application_sha": _git_head(),
            "call_caps": {"deepseek": PLAN.deepseek_calls, "jev": PLAN.jev_calls},
            "required_jev_modes": REQUIRED_JEV_MODES,
            "all_other_jev_definitions": "off",
            "conservative_deepseek_ceiling": ceiling,
        }
    )
    return result


def _run_live(args: argparse.Namespace, ceiling: float, preflight: dict[str, Any]) -> int:
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    state_path = run_dir / "run-state.json"
    prior = _prior_summary(args.prior_c1_c2_summary)
    state: dict[str, Any] = {
        "format_version": "coursejesus.p5.c3-c5.v1",
        "status": "RUNNING",
        "started_at": _now(),
        "application_sha": _git_head(),
        "model": args.model,
        "endpoint_identity": args.base_url,
        "cost_policy": args.cost_policy,
        "approved_max_cost": args.max_cost,
        "conservative_deepseek_ceiling": ceiling,
        "currency": args.currency,
        "call_caps": {"deepseek": PLAN.deepseek_calls, "jev": PLAN.jev_calls},
        "static_preflight": preflight,
        "prior_c1_c2": prior,
    }
    _write_json(state_path, state)
    ledger = DurableTransportLedger.create(run_dir / "private-transport-ledger.json")
    budget = CallBudget.create(
        deepseek_limit=PLAN.deepseek_calls,
        jev_limit=PLAN.jev_calls,
    )
    try:
        deepseek_key = os.environ[args.deepseek_key_env]
        jev_key = os.environ[args.jev_key_env]
        os.environ["TYPESAFE_API_KEY"] = jev_key
        application = create_app(
            settings=_settings(root=run_dir, args=args, deepseek_key=deepseek_key),
            embedding_provider=FixedEmbeddingProvider(),
            auth_verifier=P5AuthVerifier(),
        )
        learning = application.state.learning
        learning.provider.transport_event_sink = lambda event: ledger.record(
            "deepseek", event
        )
        original_generate = learning.generate

        def bounded_generate(*generate_args: Any, **generate_kwargs: Any) -> Any:
            budget.claim_deepseek(str(generate_kwargs.get("role") or "UNKNOWN"))
            return original_generate(*generate_args, **generate_kwargs)

        learning.generate = bounded_generate
        learning.question_engine.metered_generate = bounded_generate
        gateway = application.state.jev_service.gateway
        gateway.transport = BoundedJevTransport(gateway.transport, budget, ledger)

        workspace_id, private_course, node_id = _seed(application, run_dir)
        live_preflight = _static_blueprints(
            application, workspace_id, private_course, node_id
        )
        if live_preflight["network_calls"] != 0:
            raise RuntimeError("P5_C3_C5_PREFLIGHT_NETWORK_ACTIVITY")

        prepared = learning.start_assessment(
            workspace_id,
            OWNER,
            AssessmentStartInput(
                operation_id=PREPARE_OPERATION,
                revision=learning.state(workspace_id, OWNER)["revision"],
                node_id=node_id,
            ),
        )
        if prepared.get("status") != "READY" or prepared.get("eligible_families") != 5:
            raise RuntimeError("P5_C5_PREPARATION_NOT_READY")
        assessment = learning.start_assessment(
            workspace_id,
            OWNER,
            AssessmentStartInput(
                operation_id=START_OPERATION,
                revision=learning.state(workspace_id, OWNER)["revision"],
                node_id=node_id,
            ),
        )
        marks = [item["marks"] for item in assessment["questions"]]
        types = [item["question_type"] for item in assessment["questions"]]
        if marks != [10, 15, 20, 25, 30] or types != [
            "MCQ_SINGLE",
            "SHORT_TEXT",
            "EXPLANATION",
            "EXPLANATION",
            "EXPLANATION",
        ]:
            raise RuntimeError("P5_C5_FROZEN_SET_MISMATCH")
        if any("review" in item or "answer" in item for item in assessment["questions"]):
            raise RuntimeError("P5_C5_PRE_SUBMIT_ANSWER_LEAK")

        database = application.state.database
        with database.connect() as connection:
            private_rows = connection.execute(
                "SELECT item.id,item.ordinal,question.id AS question_revision_id,"
                "question.answer_json FROM assessment_blueprint_items AS item "
                "JOIN assessment_question_revisions AS question "
                "ON question.id=item.question_revision_id "
                "WHERE item.blueprint_id=? ORDER BY item.ordinal",
                (assessment["blueprint_id"],),
            ).fetchall()
        answers = [
            AssessmentAnswer(
                blueprint_item_id=str(row["id"]),
                answer=str(json.loads(row["answer_json"])["reference_answer"]),
            )
            for row in private_rows
        ]
        graded = learning.submit_assessment(
            workspace_id,
            OWNER,
            str(assessment["id"]),
            AssessmentSubmitInput(
                operation_id=SUBMIT_OPERATION,
                revision=learning.state(workspace_id, OWNER)["revision"],
                answers=answers,
            ),
        )
        if graded.get("status") != "GRADED" or any(
            not item.get("review", {}).get("reference_solution")
            for item in graded.get("questions", [])
        ):
            raise RuntimeError("P5_C5_GRADING_NOT_COMPLETE")

        runtime = learning.question_engine
        original_select = runtime._select_prototype

        def force_rule_prototype(self: Any, **_kwargs: Any) -> Any:
            return _PROTOTYPES["rule_violation_analysis"]

        runtime._select_prototype = MethodType(force_rule_prototype, runtime)
        try:
            rule = runtime.generate_one(
                owner_user_id=OWNER,
                workspace_id=workspace_id,
                course_id=COURSE,
                private_course_id=private_course,
                node_id=node_id,
                operation_id=RULE_OPERATION,
            )
        finally:
            runtime._select_prototype = original_select
        if rule.get("status") != "READY" or rule.get("prototype_id") != "rule_violation_analysis":
            raise RuntimeError("P5_C4_RULE_NOT_READY")
        if "rule_violation_analysis" in rule.get("public", {}):
            raise RuntimeError("P5_C4_PRIVATE_ANALYSIS_LEAK")

        with database.connect() as connection:
            model_runs = _rows(
                connection,
                "SELECT operation_id,role,model_id,provider_label,protocol,region_label,"
                "template_version,schema_version,input_hash,started_at,finished_at,latency_ms,"
                "input_tokens,output_tokens,status,error_class,provider_response_id "
                "FROM learning_model_run_evidence ORDER BY started_at,rowid",
            )
            reservations = _rows(
                connection,
                "SELECT operation_id,role,status,input_tokens,output_tokens,finished_at "
                "FROM learning_model_call_reservations ORDER BY created_at,rowid",
            )
            receipts = _rows(
                connection,
                "SELECT id,definition_key,mode,caller_role,course_id,workspace_id,node_id,"
                "spec_version,question_hash,input_hash,outcome,latency_ms,model_version "
                "FROM jev_decision_receipts WHERE definition_key IN (?,?,?,?) "
                "ORDER BY created_at,rowid",
                tuple(REQUIRED_JEV_MODES),
            )
            provenance = _rows(
                connection,
                "SELECT provenance.question_revision_id,provenance.blueprint_json,"
                "provenance.validation_report_json,provenance.publication_status,"
                "question.prompt_text,question.options_json,question.answer_json "
                "FROM question_engine_provenance AS provenance "
                "JOIN assessment_question_revisions AS question "
                "ON question.id=provenance.question_revision_id ORDER BY question.rowid",
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if (
            len(budget.deepseek_roles) != PLAN.deepseek_calls
            or len(budget.jev_definitions) != PLAN.jev_calls
            or len(model_runs) != PLAN.deepseek_calls
            or len(reservations) != PLAN.deepseek_calls
        ):
            raise RuntimeError("P5_C3_C5_CALL_COUNT_MISMATCH")
        if any(row["status"] != "COMPLETED" for row in model_runs + reservations):
            raise RuntimeError("P5_C3_C5_NONCOMPLETED_MODEL_CALL")
        if any(row["mode"] != "on" or row["outcome"] != "ok" for row in receipts):
            raise RuntimeError("P5_C3_C5_JEV_RECEIPT_MISMATCH")
        definitions = [row["definition_key"] for row in receipts]
        if (
            definitions.count("question.ambiguity.v1") != 6
            or definitions.count("question.answer_agreement.v1") != 6
            or definitions.count("question.mcq_distractor_quality.v1") != 1
            or definitions.count("question.rule_violation_quality.v1") != 1
            or len(definitions) != PLAN.jev_calls
        ):
            raise RuntimeError("P5_C3_C5_JEV_DEFINITION_COUNT_MISMATCH")
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("P5_C3_C5_DATABASE_INTEGRITY_FAILED")

        private_review = {
            "classification": "PRIVATE_HUMAN_REVIEW_MATERIAL",
            "synthetic_evidence": True,
            "case_ids": ["C3", "C4", "C5"],
            "assessment": graded,
            "rule_question": rule,
            "question_provenance": provenance,
            "human_decision": {
                "status": "PENDING_OWNER_REVIEW",
                "allowed_values": ["PASS", "REVISE", "REJECT"],
                "reason": None,
            },
        }
        _write_json(run_dir / "private-review.json", private_review)
        usage = _actual_cost(
            model_runs,
            input_price=args.input_price_per_million,
            output_price=args.output_price_per_million,
        )
        public_summary = {
            "format_version": "coursejesus.p5.c3-c5.public.v1",
            "status": "LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
            "application_sha": state["application_sha"],
            "started_at": state["started_at"],
            "finished_at": _now(),
            "model": args.model,
            "endpoint_identity": args.base_url,
            "cost_policy": args.cost_policy,
            "currency": args.currency,
            "conservative_deepseek_ceiling": ceiling,
            "actual_usage": usage,
            "deepseek_call_roles": budget.deepseek_roles,
            "jev_call_definitions": budget.jev_definitions,
            "model_run_evidence": model_runs,
            "model_call_reservations": reservations,
            "jev_receipts": receipts,
            "assessment_session_id": assessment["id"],
            "assessment_question_revision_ids": [
                row["question_revision_id"] for row in private_rows
            ],
            "assessment_marks": marks,
            "assessment_types": types,
            "assessment_raw_score": graded.get("raw_score"),
            "rule_question_revision_id": rule["question_revision_id"],
            "pre_submit_answer_hidden": True,
            "private_mcq_mapping_persisted": True,
            "private_rule_analysis_persisted": True,
            "database_integrity": integrity,
            "foreign_key_violations": [],
            "private_review_sha256": hashlib.sha256(
                (run_dir / "private-review.json").read_bytes()
            ).hexdigest(),
            "transport_ledger": ledger.public_summary(),
            "prior_c1_c2": prior,
            "human_content_review": "PENDING",
        }
        _write_json(run_dir / "public-summary.json", public_summary)
        state.update(
            status="LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
            finished_at=_now(),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            public_summary=str(run_dir / "public-summary.json"),
            private_review=str(run_dir / "private-review.json"),
            call_budget_audit=budget.audit_snapshot(),
            transport_ledger=ledger.public_summary(),
        )
        _write_json(state_path, state)
        print(f"P5 C3/C4/C5 live run completed; owner review required: {run_dir}")
        return 0
    except Exception as error:  # noqa: BLE001 - preserve partial paid evidence
        state.update(
            status="FAILED_SAFE",
            finished_at=_now(),
            error_class=type(error).__name__,
            error_code=(
                str(error)
                if str(error).startswith("P5_") and " " not in str(error)
                else "UNCLASSIFIED"
            ),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            call_budget_audit=budget.audit_snapshot(),
            transport_ledger=ledger.public_summary(),
        )
        _write_json(state_path, state)
        print(f"P5 C3/C4/C5 live run stopped safely: {type(error).__name__}")
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ceiling, errors = _validate(args)
    if errors:
        for error in errors:
            print(error)
        return 2
    try:
        preflight = _preflight(args, ceiling)
    except Exception as error:  # noqa: BLE001 - fail closed before network
        print(f"Static preflight failed: {type(error).__name__}")
        return 2
    print("Static preflight: " + json.dumps(preflight, ensure_ascii=False, sort_keys=True))
    if args.preflight_only or not args.allow_billable:
        return 0
    assert ceiling is not None
    return _run_live(args, ceiling, preflight)


if __name__ == "__main__":
    raise SystemExit(main())
