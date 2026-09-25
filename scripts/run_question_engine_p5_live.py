"""Bounded P5 live runner for the actual Question Engine C1/C2 path.

Default execution is a no-network preflight.  A live run requires an explicit
billable flag, two protected credential variables, owner-supplied prices and a
new output directory.  Provider and Jev calls are bounded independently and
never retried by this runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.deepseek_canary import (
    COST_POLICIES,
    COST_POLICY_CAPPED,
    COST_POLICY_OWNER_AUTHORIZED_UNLIMITED,
)
from app.evaluation.provider_safety import validate_deepseek_base_url


@dataclass(frozen=True, slots=True)
class LivePlan:
    name: str
    deepseek_calls: int
    jev_calls: int
    input_tokens_per_call: int
    output_tokens_per_call: int
    cases: tuple[str, ...]


REQUIRED_JEV_MODES: dict[str, str] = {
    "question.ambiguity.v1": "on",
    "question.answer_agreement.v1": "on",
    "question.mcq_distractor_quality.v1": "on",
    "question.rule_violation_quality.v1": "on",
}

# These optional selection/retrieval/citation signals default to ``shadow`` in the
# catalogue, which still performs a paid transport call.  C1/C2 does not use
# their suggestions, so the acceptance harness turns them off explicitly.  It
# leaves production defaults untouched and keeps the four P5 publication gates
# above in real ``on`` mode.
NON_REQUIRED_JEV_MODES_OFF: dict[str, str] = {
    "retrieval.support.v1": "off",
    "source.select_span.v1": "off",
    "exercise.prototype.v1": "off",
}

C1_C2_PLAN = LivePlan(
    name="question-engine-p5-c1-c2",
    deepseek_calls=8,
    jev_calls=4,
    input_tokens_per_call=15_000,
    output_tokens_per_call=4_000,
    cases=(
        "C1: actual author -> blind solve -> hard gates -> persisted Jev -> READY",
        "C2: independent attempt -> hint -> assisted attempt -> reveal -> detail -> refresh -> repractice",
    ),
)


def conservative_cost_ceiling(
    plan: LivePlan,
    *,
    input_price_per_million: float,
    output_price_per_million: float,
) -> float:
    return plan.deepseek_calls * (
        plan.input_tokens_per_call * input_price_per_million
        + plan.output_tokens_per_call * output_price_per_million
    ) / 1_000_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--deepseek-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--jev-key-env", default="TYPESAFE_API_KEY")
    parser.add_argument("--max-output-tokens", type=int, default=4_000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-deepseek-calls", type=int, default=C1_C2_PLAN.deepseek_calls)
    parser.add_argument("--max-jev-calls", type=int, default=C1_C2_PLAN.jev_calls)
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--max-cost", type=float)
    parser.add_argument(
        "--cost-policy",
        choices=list(COST_POLICIES),
        default=COST_POLICY_CAPPED,
    )
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--prior-run-state", type=Path)
    return parser.parse_args(argv)


def _positive_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prior_attempt_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("status") != "FAILED_SAFE":
        raise ValueError("Prior run state must be a FAILED_SAFE P5 state object.")
    audit = payload.get("call_budget_audit")
    if not isinstance(audit, dict):
        raise TypeError("Prior run state is missing its call budget audit.")
    return {
        "state_sha256": hashlib.sha256(raw).hexdigest(),
        "application_sha": payload.get("application_sha"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "status": payload.get("status"),
        "error_class": payload.get("error_class"),
        "error_code": payload.get("error_code"),
        "deepseek_calls": payload.get("deepseek_calls"),
        "jev_calls": payload.get("jev_calls"),
        "call_budget_audit": audit,
    }


def _configure_process_environment(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    deepseek_key: str,
    jev_key: str,
    conservative_ceiling: float,
) -> None:
    """Configure both V3 and mounted UI providers from the same frozen bounds."""

    os.environ["TYPESAFE_API_KEY"] = jev_key
    os.environ["CMUI_DATA_DIR"] = str(run_dir / "ui-extension")
    os.environ["CMUI_ENV"] = "development"
    os.environ["CMUI_PROVIDER_MODE"] = "deepseek"
    os.environ["CMUI_ALLOW_BILLABLE"] = "true"
    os.environ["CMUI_DEEPSEEK_API_KEY"] = deepseek_key
    os.environ["CMUI_DEEPSEEK_BASE_URL"] = args.base_url
    os.environ["CMUI_DEEPSEEK_MODEL"] = args.model
    os.environ["CMUI_DEEPSEEK_PROTOCOL"] = "responses"
    os.environ["CMUI_MODEL_TIMEOUT"] = str(args.timeout)
    os.environ["CMUI_ANSWER_TOKENS"] = str(args.max_output_tokens)
    os.environ["CMUI_OPERATION_USD_BASELINE"] = f"{conservative_ceiling:.8f}"
    os.environ["CMUI_OPERATION_INPUT_USD_PER_MILLION"] = str(
        args.input_price_per_million
    )
    os.environ["CMUI_OPERATION_OUTPUT_USD_PER_MILLION"] = str(
        args.output_price_per_million
    )
    os.environ["CMUI_AUTO_VERIFY_NEW_USERS"] = "false"


def _safe_error_code(error: Exception) -> str:
    value = str(error)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", value) else "UNCLASSIFIED"


@dataclass(slots=True)
class CallBudget:
    deepseek_limit: int
    jev_limit: int
    deepseek_roles: list[str]
    jev_definitions: list[str]

    @classmethod
    def create(cls, *, deepseek_limit: int, jev_limit: int) -> CallBudget:
        return cls(deepseek_limit, jev_limit, [], [])

    def claim_deepseek(self, role: str) -> None:
        if len(self.deepseek_roles) >= self.deepseek_limit:
            raise RuntimeError("P5_DEEPSEEK_CALL_CAP_REACHED")
        self.deepseek_roles.append(role)

    def claim_jev(self, definition: str) -> None:
        if len(self.jev_definitions) >= self.jev_limit:
            raise RuntimeError("P5_JEV_CALL_CAP_REACHED")
        self.jev_definitions.append(definition)

    def audit_snapshot(self) -> dict[str, Any]:
        """Return the exact attempted-call ledger without credentials or content."""

        return {
            "deepseek_limit": self.deepseek_limit,
            "deepseek_attempted_roles": list(self.deepseek_roles),
            "jev_limit": self.jev_limit,
            "jev_attempted_definitions": list(self.jev_definitions),
        }


class BoundedJevTransport:
    def __init__(self, inner: Any, budget: CallBudget) -> None:
        self.inner = inner
        self.budget = budget

    @property
    def model_version(self) -> str | None:
        return getattr(self.inner, "model_version", None)

    def call(self, call: Any, *, timeout_seconds: float) -> Any:
        definition = next(iter(call.questions), "UNKNOWN")
        self.budget.claim_jev(str(definition))
        return self.inner.call(call, timeout_seconds=timeout_seconds)


def _print_plan(args: argparse.Namespace, ceiling: float | None) -> None:
    mode = "LIVE_REQUESTED" if args.allow_billable and not args.preflight_only else "PREFLIGHT_ONLY"
    print(f"P5 Question Engine {mode}")
    print(f"Model: {args.model} @ {args.base_url}")
    print(f"DeepSeek calls: at most {C1_C2_PLAN.deepseek_calls}")
    print(f"Jev calls: at most {C1_C2_PLAN.jev_calls}")
    print(f"Output tokens per DeepSeek call: at most {args.max_output_tokens}")
    if ceiling is None:
        print("Conservative cost ceiling: UNKNOWN (explicit prices not supplied)")
    else:
        print(f"Conservative DeepSeek ceiling: {args.currency} {ceiling:.8f}")
    for case in C1_C2_PLAN.cases:
        print(f"- {case}")
    print("Stop conditions: first failed/unknown provider call, call cap, cost cap, or receipt mismatch")


def _validate(args: argparse.Namespace) -> tuple[float | None, list[str]]:
    errors: list[str] = []
    try:
        args.base_url = validate_deepseek_base_url(args.base_url)
    except ValueError as error:
        errors.append(str(error))
    if args.model != "deepseek-flash":
        errors.append("Only the verified deepseek-flash model is accepted.")
    if not 500 <= args.max_output_tokens <= 8_000:
        errors.append("--max-output-tokens must be between 500 and 8000.")
    if not 30 <= args.timeout <= 600:
        errors.append("--timeout must be between 30 and 600 seconds.")
    if args.max_deepseek_calls != C1_C2_PLAN.deepseek_calls:
        errors.append(
            f"--max-deepseek-calls must equal the frozen plan value {C1_C2_PLAN.deepseek_calls}."
        )
    if args.max_jev_calls != C1_C2_PLAN.jev_calls:
        errors.append(f"--max-jev-calls must equal the frozen plan value {C1_C2_PLAN.jev_calls}.")
    prices = (args.input_price_per_million, args.output_price_per_million)
    if (prices[0] is None) != (prices[1] is None):
        errors.append("Both input and output prices must be supplied together.")
    if any(value is not None and not _positive_finite(value) for value in prices):
        errors.append("Prices must be finite and positive.")
    ceiling = None
    if prices[0] is not None and prices[1] is not None:
        ceiling = conservative_cost_ceiling(
            LivePlan(
                name=C1_C2_PLAN.name,
                deepseek_calls=C1_C2_PLAN.deepseek_calls,
                jev_calls=C1_C2_PLAN.jev_calls,
                input_tokens_per_call=C1_C2_PLAN.input_tokens_per_call,
                output_tokens_per_call=args.max_output_tokens,
                cases=C1_C2_PLAN.cases,
            ),
            input_price_per_million=prices[0],
            output_price_per_million=prices[1],
        )
    if args.allow_billable and not args.preflight_only:
        if args.cost_policy == COST_POLICY_CAPPED:
            if not _positive_finite(args.max_cost):
                errors.append("--max-cost is required and must be positive for capped policy.")
            elif ceiling is not None and ceiling > args.max_cost:
                errors.append(
                    f"Conservative {args.currency} ceiling {ceiling:.8f} exceeds --max-cost."
                )
        elif args.cost_policy != COST_POLICY_OWNER_AUTHORIZED_UNLIMITED:
            errors.append("Unknown cost policy.")
        if ceiling is None:
            errors.append("Explicit input/output prices are required for a billable run.")
        missing = [
            name
            for name in (args.deepseek_key_env, args.jev_key_env)
            if not os.environ.get(name)
        ]
        if missing:
            errors.append("Missing protected credential environment variable(s): " + ", ".join(missing))
        if args.run_dir.exists():
            errors.append("Refusing to overwrite an existing run directory.")
        if args.prior_run_state is not None:
            try:
                _prior_attempt_summary(args.prior_run_state)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"Invalid --prior-run-state: {error}")
    return ceiling, errors


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _expect(response: Any, status: int, label: str) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"{label}_HTTP_{response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"{label}_INVALID_JSON")
    return payload


def _wait_terminal(client: Any, run_id: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = _expect(
            client.get(f"/ui-extension/api/ui/v1/runs/{run_id}", headers=headers),
            200,
            "RUN_STATUS",
        )
        if row.get("status") in {"completed", "failed", "cancelled"}:
            return row
        time.sleep(0.2)
    raise RuntimeError("P5_RUN_TIMEOUT")


def _seed_synthetic_objective(application: Any, course_id: str, owner: str, run_dir: Path) -> str:
    from app.learning.workspaces import join_course

    database = application.state.database
    workspace = join_course(database, course_id, owner, 10)
    node_id = "p5-node-density"
    source_text = (
        "Synthetic acceptance material. In DBSCAN, the epsilon-neighbourhood of a point includes "
        "all points within distance epsilon, including the point itself. A core point has at least "
        "MinPts points in that neighbourhood. For epsilon=1.5 and MinPts=3, the distances from "
        "point A to A, B, C and D are 0, 1.0, 1.4 and 2.2 respectively."
    )
    source_dir = run_dir / "synthetic-source"
    source_dir.mkdir()
    source_file = source_dir / "dbscan-acceptance.md"
    source_file.write_text(source_text + "\n", encoding="utf-8")
    item = {
        "item_id": "p5-objective-density",
        "requirement": "REQUIRED",
        "objective": (
            "Use the stated epsilon and MinPts rule to count A's neighbourhood and decide whether "
            "A is a core point."
        ),
        "acceptance": (
            "The answer must include the eligible distances, the neighbourhood count, and the "
            "core-point conclusion from the supplied rule."
        ),
        "evidence_ids": ["p5-chunk-density"],
    }
    specification = json.dumps([item], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(source_text.encode()).hexdigest()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) "
            "VALUES(?,?,?,'DBSCAN core points','P5 synthetic acceptance evidence','CS','ATOMIC','PRIVATE')",
            (node_id, course_id, owner),
        )
        connection.execute(
            "INSERT INTO documents(id,course_id,filename,stored_path,media_type,extension,sha256,"
            "byte_size,status,chunk_count) VALUES(?,?,?,?,?,?,?,?, 'ready',1)",
            (
                "p5-doc-density",
                course_id,
                source_file.name,
                str(source_file),
                "text/markdown",
                ".md",
                digest,
                len(source_text.encode()),
            ),
        )
        connection.execute(
            "INSERT INTO chunks(id,document_id,course_id,ordinal,content,locator_type,locator_value,"
            "section,embedding) VALUES('p5-chunk-density','p5-doc-density',?,0,?,'section','1',"
            "'Synthetic DBSCAN acceptance','[]')",
            (course_id, source_text),
        )
        connection.execute(
            "INSERT INTO teaching_specs(node_id,version,content_json,content_hash) VALUES(?,1,?,?)",
            (node_id, specification, hashlib.sha256(specification.encode()).hexdigest()),
        )
    if str(workspace["course_id"]) != course_id:
        raise RuntimeError("P5_WORKSPACE_COURSE_MISMATCH")
    return node_id


def _rows(connection: Any, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def _actual_cost(
    run_rows: list[dict[str, Any]],
    explanation_usage: list[dict[str, Any]],
    *,
    input_price: float,
    output_price: float,
) -> dict[str, Any]:
    usage: list[tuple[int, int]] = []
    complete = True
    for row in run_rows:
        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        if input_tokens <= 0 and output_tokens <= 0:
            complete = False
        usage.append((input_tokens, output_tokens))
    explanation_actual = [
        item
        for item in explanation_usage
        if isinstance(item, dict)
        and ("input_tokens" in item or "output_tokens" in item)
        and not item.get("estimated")
    ]
    if len(explanation_actual) != 1:
        complete = False
    else:
        item = explanation_actual[0]
        input_tokens = int(item.get("input_tokens") or 0)
        output_tokens = int(item.get("output_tokens") or 0)
        if input_tokens <= 0 and output_tokens <= 0:
            complete = False
        usage.append((input_tokens, output_tokens))
    input_total = sum(item[0] for item in usage)
    output_total = sum(item[1] for item in usage)
    return {
        "input_tokens": input_total,
        "output_tokens": output_total,
        "cost_estimated_at_owner_prices": (
            (input_total * input_price + output_total * output_price) / 1_000_000
            if complete
            else None
        ),
        "cost_basis": (
            "ESTIMATED_FROM_RECORDED_TOKENS_AT_OWNER_PRICES"
            if complete
            else "UNKNOWN_INCOMPLETE_USAGE"
        ),
    }


def _run_c1_c2(args: argparse.Namespace, ceiling: float) -> int:
    from app.config import Settings
    from app.main import create_app
    from fastapi import Request
    from fastapi.testclient import TestClient

    owner = "p5-synthetic-owner"
    auth_headers = {"Authorization": "Bearer p5-synthetic-token"}
    api = "/ui-extension/api/ui/v1"
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    state_path = run_dir / "run-state.json"
    started_at = _now()
    state: dict[str, Any] = {
        "format_version": "coursejesus.p5.c1-c2.v1",
        "status": "RUNNING",
        "started_at": started_at,
        "application_sha": _git_head(),
        "model": args.model,
        "endpoint_identity": args.base_url,
        "cost_policy": args.cost_policy,
        "approved_max_cost": args.max_cost,
        "conservative_deepseek_ceiling": ceiling,
        "currency": args.currency,
        "required_jev_modes": REQUIRED_JEV_MODES,
        "private_material_location": str(run_dir / "private-review.json"),
    }
    prior_attempt = _prior_attempt_summary(args.prior_run_state)
    if prior_attempt is not None:
        state["prior_attempt"] = prior_attempt
    _write_json(state_path, state)

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
    _configure_process_environment(
        args,
        run_dir=run_dir,
        deepseek_key=deepseek_key,
        jev_key=jev_key,
        conservative_ceiling=ceiling,
    )

    modes = ",".join(
        f"{key}={value}"
        for key, value in (REQUIRED_JEV_MODES | NON_REQUIRED_JEV_MODES_OFF).items()
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
    budget = CallBudget.create(
        deepseek_limit=args.max_deepseek_calls,
        jev_limit=args.max_jev_calls,
    )
    try:
        application = create_app(
            settings=settings,
            embedding_provider=FixedEmbeddingProvider(),
            auth_verifier=P5AuthVerifier(),
        )
        learning = application.state.learning
        original_generate = learning.generate

        def bounded_generate(*generate_args: Any, **generate_kwargs: Any) -> Any:
            budget.claim_deepseek(str(generate_kwargs.get("role") or "UNKNOWN"))
            return original_generate(*generate_args, **generate_kwargs)

        learning.question_engine.metered_generate = bounded_generate
        gateway = application.state.jev_service.gateway
        gateway.transport = BoundedJevTransport(gateway.transport, budget)

        ui_model = application.state.ui_extension_app.state.provider
        original_explanation = ui_model.generate_explanation

        async def bounded_explanation(*model_args: Any, **model_kwargs: Any) -> Any:
            budget.claim_deepseek("EXPLANATION")
            async for event in original_explanation(*model_args, **model_kwargs):
                yield event

        ui_model.generate_explanation = bounded_explanation

        with TestClient(application) as client:
            course = _expect(
                client.post(
                    f"{api}/courses",
                    headers=auth_headers,
                    json={
                        "name": "P5 synthetic DBSCAN acceptance",
                        "description": "Isolated generated-content acceptance only",
                    },
                ),
                201,
                "COURSE_CREATE",
            )
            course_id = str(course["id"])
            node_id = _seed_synthetic_objective(application, course_id, owner, run_dir)
            pair = _expect(
                client.post(f"{api}/pairs", headers=auth_headers, json={"course": course_id}),
                201,
                "PAIR_CREATE",
            )
            pair_id = str(pair["id"])
            database = application.state.database
            with database.connect() as connection:
                before_counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("grade_snapshots", "performance_evidence", "learning_coverage")
                }

            first_start = _expect(
                client.post(
                    f"{api}/courses/{course_id}/exercises",
                    headers=auth_headers,
                    json={
                        "pair_id": pair_id,
                        "node": node_id,
                        "request_id": "p5-question-c1-0001",
                    },
                ),
                202,
                "C1_START",
            )
            first_run = _wait_terminal(client, str(first_start["id"]), auth_headers, args.timeout)
            if first_run.get("status") != "completed":
                raise RuntimeError("C1_QUESTION_NOT_COMPLETED")
            ui_database = application.state.ui_extension_app.state.db
            exercise = ui_database.one(
                "SELECT * FROM cmui_exercises WHERE run=?", (first_start["id"],)
            )
            if not exercise or not exercise.get("question_revision_id"):
                raise RuntimeError("C1_EXERCISE_MISSING")
            exercise_id = str(exercise["id"])
            question_revision_id = str(exercise["question_revision_id"])
            stored_steps = json.loads(str(exercise["answer_steps"]))
            private_texts = [str(step["text"]) for step in stored_steps]
            events = ui_database.all(
                "SELECT type,data FROM cmui_run_events WHERE run=? ORDER BY seq",
                (first_start["id"],),
            )
            public_events = json.dumps(events, ensure_ascii=False)
            hidden = _expect(
                client.get(f"{api}/exercises/{exercise_id}", headers=auth_headers),
                200,
                "C1_HIDDEN",
            )
            if hidden.get("steps") != [] or any(text in public_events for text in private_texts):
                raise RuntimeError("C1_PRIVATE_ANSWER_LEAK")

            independent = _expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/attempts",
                    headers=auth_headers,
                    json={
                        "request_id": "p5-attempt-independent-0001",
                        "answer": (
                            "A has two neighbours within epsilon, so I think it is not a core point."
                        ),
                    },
                ),
                200,
                "C2_INDEPENDENT_ATTEMPT",
            )
            if independent.get("assistance") != "NONE" or independent.get("independent") is not True:
                raise RuntimeError("C2_INDEPENDENT_MARKING_INVALID")
            hint = _expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/hints",
                    headers=auth_headers,
                    json={"request_id": "p5-hint-0001"},
                ),
                200,
                "C2_HINT",
            )
            if any(text in json.dumps(hint, ensure_ascii=False) for text in private_texts):
                raise RuntimeError("C2_HINT_EXACT_ANSWER_LEAK")
            assisted = _expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/attempts",
                    headers=auth_headers,
                    json={
                        "request_id": "p5-attempt-assisted-0001",
                        "answer": (
                            "I now count A itself plus B and C, giving three points, so A is core."
                        ),
                    },
                ),
                200,
                "C2_ASSISTED_ATTEMPT",
            )
            if assisted.get("assistance") != "HINT" or assisted.get("independent") is not False:
                raise RuntimeError("C2_ASSISTANCE_MARKING_INVALID")
            revealed = _expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/reveal",
                    headers=auth_headers,
                    json={"request_id": "p5-reveal-0001"},
                ),
                200,
                "C2_REVEAL",
            )
            if revealed.get("steps") != stored_steps:
                raise RuntimeError("C2_REVEAL_MISMATCH")
            detail_start = _expect(
                client.post(
                    f"{api}/exercises/{exercise_id}/steps/{stored_steps[0]['step_id']}/explanation",
                    headers=auth_headers,
                    json={"request_id": "p5-detail-0001"},
                ),
                202,
                "C2_DETAIL_START",
            )
            detail_run = _wait_terminal(
                client, str(detail_start["run"]), auth_headers, args.timeout
            )
            if detail_run.get("status") != "completed":
                raise RuntimeError("C2_DETAIL_NOT_COMPLETED")
            detail = _expect(
                client.get(f"{api}/explanations/{detail_start['id']}", headers=auth_headers),
                200,
                "C2_DETAIL",
            )
            if not str(detail.get("text") or "").strip():
                raise RuntimeError("C2_DETAIL_EMPTY")

            restored = _expect(
                client.get(f"{api}/exercises/{exercise_id}", headers=auth_headers),
                200,
                "C2_RESTORE",
            )
            if restored.get("hint_count") != 1 or not restored.get("latest_attempt"):
                raise RuntimeError("C2_RESTORE_INCOMPLETE")
            conversation = ui_database.one(
                "SELECT conversation FROM cmui_messages WHERE exercise=?", (exercise_id,)
            )
            history = _expect(
                client.get(
                    f"{api}/conversations/{conversation['conversation']}", headers=auth_headers
                ),
                200,
                "C2_HISTORY",
            )
            if not any(
                item.get("exercise") == exercise_id and item.get("exercise_state")
                for item in history.get("messages", [])
            ):
                raise RuntimeError("C2_HISTORY_STATE_MISSING")

            second_start = _expect(
                client.post(
                    f"{api}/courses/{course_id}/exercises",
                    headers=auth_headers,
                    json={
                        "pair_id": pair_id,
                        "node": node_id,
                        "request_id": "p5-question-c2-repractice-0001",
                    },
                ),
                202,
                "C2_REPRACTICE_START",
            )
            second_run = _wait_terminal(
                client, str(second_start["id"]), auth_headers, args.timeout
            )
            if second_run.get("status") != "completed":
                raise RuntimeError("C2_REPRACTICE_NOT_COMPLETED")
            with database.connect() as connection:
                provenance = connection.execute(
                    "SELECT workspace_id FROM question_engine_provenance WHERE question_revision_id=?",
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
                    for table in ("grade_snapshots", "performance_evidence", "learning_coverage")
                }
                model_runs = _rows(
                    connection,
                    "SELECT role,model_id,provider_label,protocol,region_label,template_version,"
                    "schema_version,input_hash,started_at,finished_at,latency_ms,input_tokens,"
                    "output_tokens,status,error_class,provider_response_id "
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
                    "FROM jev_decision_receipts ORDER BY created_at,rowid",
                )
                validation_rows = _rows(
                    connection,
                    "SELECT question_revision_id,validation_report_json,publication_status "
                    "FROM question_engine_provenance ORDER BY rowid",
                )
                rubric = _rows(
                    connection,
                    "SELECT criterion_id,dimension,max_fraction,description "
                    "FROM assessment_rubric_criteria WHERE question_revision_id=? "
                    "ORDER BY criterion_id",
                    (question_revision_id,),
                )
            if before_counts != after_counts:
                raise RuntimeError("C2_PRACTICE_MUTATED_FORMAL_PROGRESS")
            if len({str(row["family_id"]) for row in family_rows}) != 2:
                raise RuntimeError("C2_REPRACTICE_FAMILY_NOT_NEW")
            if len(budget.deepseek_roles) != C1_C2_PLAN.deepseek_calls:
                raise RuntimeError("P5_DEEPSEEK_CALL_COUNT_MISMATCH")
            if len(budget.jev_definitions) != C1_C2_PLAN.jev_calls:
                raise RuntimeError("P5_JEV_CALL_COUNT_MISMATCH")
            required_receipts = [
                row for row in receipts if row["definition_key"] in REQUIRED_JEV_MODES
            ]
            if len(required_receipts) != 4 or any(
                row["mode"] != "on" or row["outcome"] != "ok" for row in required_receipts
            ):
                raise RuntimeError("P5_REQUIRED_JEV_RECEIPT_MISMATCH")

            raw_explanation_usage = detail_run.get("usage") or []
            explanation_usage = (
                json.loads(raw_explanation_usage)
                if isinstance(raw_explanation_usage, str)
                else raw_explanation_usage
            )
            costs = _actual_cost(
                model_runs,
                explanation_usage if isinstance(explanation_usage, list) else [],
                input_price=args.input_price_per_million,
                output_price=args.output_price_per_million,
            )
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
                "human_decision": {
                    "status": "PENDING_OWNER_REVIEW",
                    "allowed_values": ["PASS", "REVISE", "REJECT"],
                    "reason": None,
                },
            }
            _write_json(run_dir / "private-review.json", private_review)
            public_summary = {
                "format_version": "coursejesus.p5.c1-c2.public.v1",
                "status": "LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
                "application_sha": state["application_sha"],
                "started_at": started_at,
                "finished_at": _now(),
                "model": args.model,
                "endpoint_identity": args.base_url,
                "cost_policy": args.cost_policy,
                "currency": args.currency,
                "conservative_deepseek_ceiling": ceiling,
                "actual_usage": costs,
                "deepseek_call_roles": budget.deepseek_roles,
                "jev_call_definitions": budget.jev_definitions,
                "required_jev_receipts": required_receipts,
                "model_run_evidence": model_runs,
                "model_call_reservations": reservations,
                "question_revision_ids": [row["question_revision_id"] for row in validation_rows],
                "question_content_sha256": hashlib.sha256(
                    str(exercise["question"]).encode()
                ).hexdigest(),
                "private_answer_sha256": hashlib.sha256(
                    json.dumps(stored_steps, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
                "answer_hidden_before_reveal": True,
                "exact_answer_absent_from_hint": True,
                "practice_did_not_change_formal_progress": True,
                "refresh_history_restored": True,
                "different_family_repractice": True,
                "human_content_review": "PENDING",
                "prior_attempt": prior_attempt,
                "cumulative_attempted_calls": {
                    "deepseek": len(budget.deepseek_roles)
                    + int((prior_attempt or {}).get("deepseek_calls") or 0),
                    "jev": len(budget.jev_definitions)
                    + int((prior_attempt or {}).get("jev_calls") or 0),
                },
            }
            _write_json(run_dir / "public-summary.json", public_summary)

        state.update(
            status="LIVE_CALLS_COMPLETED_HUMAN_REVIEW_REQUIRED",
            finished_at=_now(),
            public_summary=str(run_dir / "public-summary.json"),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            call_budget_audit=budget.audit_snapshot(),
        )
        _write_json(state_path, state)
        print(f"P5 C1/C2 live run completed; private human review is required: {run_dir}")
        return 0
    except Exception as error:  # noqa: BLE001 - terminal guard must preserve partial paid evidence
        state.update(
            status="FAILED_SAFE",
            finished_at=_now(),
            error_class=type(error).__name__,
            error_code=_safe_error_code(error),
            deepseek_calls=len(budget.deepseek_roles),
            jev_calls=len(budget.jev_definitions),
            call_budget_audit=budget.audit_snapshot(),
        )
        _write_json(state_path, state)
        print(f"P5 live run stopped safely: {type(error).__name__}")
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ceiling, errors = _validate(args)
    _print_plan(args, ceiling)
    if errors:
        for error in errors:
            print(error)
        return 2
    if args.preflight_only or not args.allow_billable:
        return 0

    assert ceiling is not None
    return _run_c1_c2(args, ceiling)


if __name__ == "__main__":
    raise SystemExit(main())
