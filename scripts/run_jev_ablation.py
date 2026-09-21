"""Run the A/B/C/D Jev ablation offline (plumbing) or live (billable, budget-capped).

Offline mode (``--transport deterministic_fake``) needs zero credentials and produces
a result tagged NON_INTERPRETABLE_PLUMBING_ONLY. Live mode requires ``--allow-billable``,
computes a worst-case cost ceiling BEFORE any call, reads its key only from the named
environment variable, and never writes a key into the result file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.jev_ablation import (
    ARM_NAMES,
    DATASET_STATUS_LABELLED,
    compare_arms,
    deterministic_fake_responder,
    estimate_input_token_ceilings,
    load_ablation_cases,
    run_ablation,
)
from app.evaluation.model_benchmark import calculate_cost_ceiling
from app.jev.gateway import FakeTransport, SdkTransport

EXAMPLE_CASES = ROOT / "benchmarks" / "jev-ablation-cases.example.json"
DEFAULT_OUTPUT = ROOT / "work" / "current-change" / "jev-ablation-offline.json"
MAX_JEV_OUTPUT_TOKENS = 256
PROTOCOL_OVERHEAD_TOKENS = 512
DEFAULT_JEV_API_KEY_ENV = "TYPESAFE_API_KEY"


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=[*ARM_NAMES, "all"], default="all")
    parser.add_argument("--cases", type=Path, default=EXAMPLE_CASES)
    parser.add_argument(
        "--transport", choices=["deterministic_fake", "live"], default="deterministic_fake"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--jev-input-price-per-million", type=float)
    parser.add_argument("--jev-output-price-per-million", type=float)
    parser.add_argument("--jev-api-key-env", default=DEFAULT_JEV_API_KEY_ENV)
    return parser.parse_args()


def _live_preflight(
    args: argparse.Namespace, cases: Any
) -> tuple[float, str | None]:
    """Validate billable authorization and compute the ceiling BEFORE any call."""
    if not args.allow_billable:
        print("Refusing provider calls: pass --allow-billable after approving charges.")
        raise SystemExit(2)
    if cases.dataset_status != DATASET_STATUS_LABELLED:
        print(
            "Refusing a live run: the case file is not a labelled dataset "
            f"(dataset_status={cases.dataset_status!r}); the example file is never "
            "interpretable."
        )
        raise SystemExit(2)
    if not math.isfinite(args.max_cost) or args.max_cost <= 0:
        print("--max-cost must be finite and positive for a live run.")
        raise SystemExit(2)
    if not math.isfinite(args.jev_input_price_per_million) or args.jev_input_price_per_million < 0:
        print("--jev-input-price-per-million must be a non-negative finite number.")
        raise SystemExit(2)
    if not math.isfinite(args.jev_output_price_per_million) or args.jev_output_price_per_million < 0:
        print("--jev-output-price-per-million must be a non-negative finite number.")
        raise SystemExit(2)

    ceilings: dict[str, float] = {}
    arms = ARM_NAMES if args.arm == "all" else [args.arm]
    for arm in arms:
        input_ceilings = estimate_input_token_ceilings(
            cases, arm, protocol_overhead_tokens=PROTOCOL_OVERHEAD_TOKENS
        )
        try:
            ceilings[arm] = calculate_cost_ceiling(
                input_ceilings,
                max_output_tokens_per_case=MAX_JEV_OUTPUT_TOKENS,
                input_price_per_million=args.jev_input_price_per_million,
                output_price_per_million=args.jev_output_price_per_million,
            )
        except ValueError as error:
            print(f"Invalid budget configuration: {error}")
            raise SystemExit(2) from error
    worst_ceiling = max(ceilings.values(), default=0.0)
    if worst_ceiling > args.max_cost:
        print(
            f"Refusing provider calls: conservative {args.currency} cost ceiling "
            f"{worst_ceiling:.8f} exceeds approved maximum {args.max_cost:.8f}."
        )
        raise SystemExit(2)

    api_key = os.environ.get(args.jev_api_key_env)
    if not api_key:
        print(f"Missing credential environment variable: {args.jev_api_key_env}")
        raise SystemExit(2)
    return worst_ceiling, api_key


def _summarize_arm(summary: dict[str, Any]) -> None:
    metrics = summary.get("metrics") or {}
    print(
        f"  arm={summary['arm']} transport={summary['transport']} "
        f"interpretation={summary['interpretation']}"
    )
    print(
        f"    recall@k={_fmt(metrics.get('recall_at_k'))} mrr={_fmt(metrics.get('mrr'))} "
        f"locator={_fmt(metrics.get('locator_accuracy'))} "
        f"citation_acc={_fmt(metrics.get('citation_support_accuracy'))} "
        f"mainline={_fmt(metrics.get('mainline_recovery_rate'))} "
        f"criterion_error={_fmt(metrics.get('criterion_error'))} "
        f"image_acc={_fmt(metrics.get('image_answer_accuracy'))} "
        f"failure_rate={_fmt(metrics.get('failure_rate'))}"
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main() -> int:
    args = parse_args()
    if args.out.exists() or args.out.with_name(f".{args.out.name}.partial").exists():
        print("Refusing to overwrite an existing ablation output or partial checkpoint.")
        return 2
    try:
        cases = load_ablation_cases(args.cases)
    except ValueError as error:
        print(f"Ablation preflight failed: {error}")
        return 2

    transport: Any
    cost_ceiling: float | None = None
    api_key: str | None = None
    if args.transport == "live":
        cost_ceiling, api_key = _live_preflight(args, cases)
        transport = SdkTransport(api_key=api_key)
    else:
        transport = FakeTransport(deterministic_fake_responder)

    arms = list(ARM_NAMES) if args.arm == "all" else [args.arm]
    arm_summaries: list[dict[str, Any]] = []
    for arm in arms:
        summary = run_ablation(cases, arm, transport=transport)
        arm_summaries.append(summary)

    runs = {summary["arm"]: summary for summary in arm_summaries}
    comparison = compare_arms(runs)

    print(f"Ablation: transport={args.transport} arms={','.join(arms)}")
    for summary in arm_summaries:
        _summarize_arm(summary)
    print(f"comparison verdict={comparison['verdict']}")

    payload: dict[str, Any] = {
        "transport": args.transport,
        "dataset_status": cases.dataset_status,
        "dataset_path": str(args.cases),
        "currency": args.currency if args.transport == "live" else None,
        "allow_billable": args.allow_billable,
        "preflight_cost_ceiling": cost_ceiling,
        "comparison": comparison,
        "arms": arm_summaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # ``api_key`` is read only to construct the transport and is never placed in
    # ``payload``, so no credential can reach the result file.
    _write_json_atomically(args.out, payload)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
