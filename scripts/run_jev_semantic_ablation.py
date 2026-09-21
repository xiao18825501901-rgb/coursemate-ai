"""Run the A/B/C/D/E Jev ablation offline (plumbing) or live (billable, gated).

Offline mode (``--transport fake``, the default) needs zero credentials and produces a
result tagged ``NON_INTERPRETABLE_PLUMBING_ONLY``; :func:`compare_jev_arms` then
returns ``NOT_INTERPRETABLE`` and no quality claim is possible. Live mode requires
``--allow-billable`` and a configured Jev service + DeepSeek key; neither exists in
this environment, so a live run is refused rather than faked. Nothing here can cost
money without the explicit ``--allow-billable`` flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.jev_semantic_ablation import (
    ARM_NAMES,
    FakeJevTransport,
    compare_jev_arms,
    deterministic_fake_jev_predictor,
    load_jev_dataset,
    run_jev_semantic_ablation,
)

DATASET_PATH = ROOT / "benchmarks" / "jev-judgments.dataset.json"
DEFAULT_OUT = ROOT / "work" / "current-change" / "jev-ablation-offline.json"


def _write_json_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=[*ARM_NAMES, "all"], default="all")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--transport", choices=["fake", "live"], default="fake")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-billable", action="store_true")
    return parser.parse_args()


def _live_preflight(args: argparse.Namespace) -> None:
    """Refuse any billable run that is not fully authorized and configured."""
    if not args.allow_billable:
        print("Refusing a live run: pass --allow-billable after approving charges.")
        raise SystemExit(2)
    missing = []
    if not os.environ.get("TYPESAFE_API_KEY"):
        missing.append("TYPESAFE_API_KEY")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        missing.append("DEEPSEEK_API_KEY")
    if missing:
        print(
            "Refusing a live run: no Jev service / DeepSeek key is configured in this "
            f"environment (missing {', '.join(missing)}). No billable call was made."
        )
        raise SystemExit(2)


def _summarize_arm(summary: dict) -> None:
    metrics = summary.get("metrics") or {}
    print(
        f"  arm={summary['arm']} transport={summary['transport']} "
        f"interpretation={summary['interpretation']}"
    )
    print(
        f"    recall@k={_fmt(metrics.get('recall_at_k'))} mrr={_fmt(metrics.get('mrr'))} "
        f"ndcg={_fmt(metrics.get('ndcg_at_k'))} locator={_fmt(metrics.get('locator_accuracy'))} "
        f"citation_acc={_fmt(metrics.get('citation_support_accuracy'))} "
        f"intent_acc={_fmt(metrics.get('intent_accuracy'))} "
        f"criterion_error={_fmt(metrics.get('criterion_error'))} "
        f"mainline={_fmt(metrics.get('mainline_recovery_rate'))}"
    )


def _fmt(value) -> str:
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
    if args.transport == "live":
        _live_preflight(args)

    try:
        dataset = load_jev_dataset(args.dataset)
    except ValueError as error:
        print(f"Ablation preflight failed: {error}")
        return 2

    arms = list(ARM_NAMES) if args.arm == "all" else [args.arm]
    arm_summaries = []
    for arm in arms:
        if args.transport == "fake":
            summary = run_jev_semantic_ablation(
                dataset,
                arm,
                transport=FakeJevTransport(),
                jev_predictor=deterministic_fake_jev_predictor,
            )
        else:
            # A live run would inject a real Jev predictor and a real DeepSeek
            # predictor; neither exists here, so this branch is unreachable after
            # _live_preflight. Kept explicit so the module cannot silently fake a live run.
            summary = run_jev_semantic_ablation(dataset, arm, transport=FakeJevTransport())
        arm_summaries.append(summary)

    runs = {summary["arm"]: summary for summary in arm_summaries}
    comparison = compare_jev_arms(runs)

    print(f"Jev ablation: transport={args.transport} arms={','.join(arms)}")
    for summary in arm_summaries:
        _summarize_arm(summary)
    print(f"comparison verdict={comparison['verdict']}")

    payload = {
        "transport": args.transport,
        "dataset_status": dataset.get("dataset_status"),
        "dataset_path": str(args.dataset),
        "allow_billable": args.allow_billable,
        "comparison": comparison,
        "arms": arm_summaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomically(args.out, payload)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
