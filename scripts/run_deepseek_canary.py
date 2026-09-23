"""Run the bounded DeepSeek generation canary against deepseek-flash.

Fail-closed, mirroring ``run_v3_model_canary.py``: no provider call is made
without an explicit billable opt-in, an allow-listed DeepSeek base URL, a
``deepseek-*`` model alias, explicit owner-supplied prices, a whole-run cost
ceiling under ``--max-cost``, and a ``DEEPSEEK_API_KEY`` read from the
environment (never echoed, never written to the evidence file).  There is at
most one provider call per role, no retries and no resume; partial evidence is
checkpointed after every completed call.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
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
    CanaryContractError,
    DeepSeekPrices,
    build_evidence,
    plan_canary,
    refusal_message,
    run_canary,
    total_cost_ceiling,
    validate_model_alias,
)
from app.evaluation.provider_safety import validate_deepseek_base_url

MODEL = "deepseek-flash"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_OUTPUT_TOKENS = 4_000
DEFAULT_OUTPUT = ROOT / "work" / "current-change" / "deepseek-canary-evidence.json"

# A 1x1 transparent PNG, used only for the IMAGE_UNDERSTANDING role's detail field.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--max-cost", type=float)
    parser.add_argument(
        "--cost-policy",
        choices=list(COST_POLICIES),
        default=COST_POLICY_CAPPED,
        help=(
            "how the spend is authorised: 'capped' requires --max-cost and refuses above it; "
            "'owner_authorized_unlimited_for_this_workflow' is the owner's explicit grant for this "
            "workflow, still records the conservative ceiling and the real usage, and is never the "
            "default"
        ),
    )
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--allow-billable", action="store_true")
    return parser.parse_args()


def _real_transport(api_key: str, timeout: float) -> Any:
    """Build the real HTTP transport; the key stays in this closure, never in evidence."""
    import httpx

    client = httpx.Client(
        timeout=httpx.Timeout(timeout, connect=12), follow_redirects=False
    )

    def transport(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = client.post(
            endpoint, headers={"Authorization": "Bearer " + api_key}, json=payload
        )
        if response.status_code != 200:
            raise RuntimeError(f"PROVIDER_HTTP_{response.status_code}")
        return response.json()

    return transport


def main() -> int:
    args = parse_args()
    # Preflight is the default: it needs no key, no prices and makes no call.
    # A billable run requires --allow-billable (with --preflight-only absent).
    preflight_only = args.preflight_only or not args.allow_billable
    if not preflight_only and not args.allow_billable:
        print("Refusing provider calls: pass --allow-billable after approving model charges.")
        return 2
    try:
        base_url = validate_deepseek_base_url(args.base_url)
    except ValueError as error:
        print(str(error))
        return 2
    try:
        validate_model_alias(args.model)
    except CanaryContractError as error:
        print(str(error))
        return 2
    if not 1 <= args.max_output_tokens <= 8_000:
        print("--max-output-tokens must be between 1 and 8000.")
        return 2

    prices: DeepSeekPrices | None = None
    if args.input_price_per_million is not None or args.output_price_per_million is not None:
        if args.input_price_per_million is None or args.output_price_per_million is None:
            print(
                "--input-price-per-million and --output-price-per-million must be "
                "supplied together (both are explicit owner prices, never invented)."
            )
            return 2
        prices = DeepSeekPrices(
            args.input_price_per_million, args.output_price_per_million, args.currency
        )

    image_data_url = "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii")
    try:
        plan = plan_canary(
            model=args.model,
            base_url=base_url,
            prices=prices,
            max_output_tokens=args.max_output_tokens,
            image_data_url=image_data_url,
        )
    except (ValueError, CanaryContractError) as error:
        print(f"Invalid DeepSeek canary configuration: {error}")
        return 2

    total_input_ceiling = sum(call.input_token_ceiling for call in plan.calls)
    if prices is not None:
        cost_ceiling = total_cost_ceiling(plan, prices)
        print(
            f"DeepSeek canary preflight: {len(plan.calls)} provider calls, "
            f"conservative {args.currency} cost ceiling {cost_ceiling:.8f}, "
            f"input-token ceiling {total_input_ceiling}, model {args.model}."
        )
    else:
        print(
            f"DeepSeek canary preflight: {len(plan.calls)} provider calls, "
            f"input-token ceiling {total_input_ceiling}, model {args.model}. "
            "Cost ceiling requires explicit --input-price-per-million and "
            "--output-price-per-million (prices are never invented)."
        )
    for call in plan.calls:
        print(f"  - {call.role}: {call.protocol} -> {call.endpoint} "
              f"(input ceiling {call.input_token_ceiling})")
    if preflight_only:
        return 0

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Missing credential environment variable: {args.api_key_env}")
        return 2
    unlimited = args.cost_policy == COST_POLICY_OWNER_AUTHORIZED_UNLIMITED
    if args.max_cost is None and not unlimited:
        print("Refusing provider calls: --max-cost is required for a billable run.")
        return 2
    if args.max_cost is not None and (not math.isfinite(args.max_cost) or args.max_cost <= 0):
        print("--max-cost must be finite and positive.")
        return 2
    if prices is None:
        print(
            "Refusing provider calls: explicit --input-price-per-million and "
            "--output-price-per-million are required for a billable run."
        )
        return 2
    cost_ceiling = total_cost_ceiling(plan, prices)
    if unlimited:
        # The owner authorized this workflow without a new USD cap. The ceiling is still computed
        # and printed, because an unlimited run has to stay an auditable one; it does not gate the
        # calls. Nothing here invents a fake limit (99999) or makes the mode the default.
        print(
            f"Cost policy: {args.cost_policy}. Worst-case {args.currency} ceiling for this plan is "
            f"{cost_ceiling:.8f}; it is recorded in the evidence and does not gate the run."
        )
    else:
        refusal = refusal_message(
            currency=args.currency, ceiling=cost_ceiling, max_cost=args.max_cost
        )
        if refusal is not None:
            print(refusal)
            return 2

    output = args.out
    partial_path = output.with_name(f".{output.name}.partial")
    checkpoint_path = output.with_name(f".{output.name}.checkpoint.json")
    if output.exists() or partial_path.exists() or checkpoint_path.exists():
        print("Refusing to overwrite an existing DeepSeek canary output or checkpoint.")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    transport = _real_transport(api_key, timeout=args.timeout)

    def checkpoint(results: list[Any]) -> None:
        evidence = build_evidence(
            plan,
            results,
            prices=prices,
            status="RUNNING",
            live_verification="NOT_VERIFIED_UNTIL_CALLS_AND_HUMAN_REVIEW_COMPLETE",
            started_at=started_at,
            approved_max_cost=args.max_cost,
            cost_policy=args.cost_policy,
        )
        _write_json_atomically(checkpoint_path, evidence)

    results = run_canary(plan, transport=transport, prices=prices, on_call=checkpoint)

    if any(result.status == "failed" for result in results):
        status = "FAILED_PROVIDER_CALL"
        live_verification = "NOT_VERIFIED"
    elif (
        all(result.status == "completed" for result in results)
        and len(results) == len(plan.calls)
    ):
        status = "LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED"
        live_verification = "PENDING_HUMAN_QUALITY_REVIEW"
    else:
        status = "LIVE_CALLS_INCOMPLETE"
        live_verification = "NOT_VERIFIED"

    finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = build_evidence(
        plan,
        results,
        prices=prices,
        status=status,
        live_verification=live_verification,
        started_at=started_at,
        finished_at=finished_at,
        approved_max_cost=args.max_cost,
        cost_policy=args.cost_policy,
    )
    _write_json_atomically(output, evidence)
    checkpoint_path.unlink()
    print(
        f"Wrote {len(results)} DeepSeek canary call records. "
        "Human quality review remains required."
    )
    return 0 if status == "LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
