"""Run the A/B/C/D/E Jev ablation (plus the six component arms) offline or live.

Offline mode (``--transport fake``, the default) needs zero credentials and produces a
result tagged ``NON_INTERPRETABLE_PLUMBING_ONLY``; :func:`compare_jev_arms` then
returns ``NOT_INTERPRETABLE`` and no quality claim is possible. Live mode requires
``--allow-billable``, a Jev key in the environment, and a **labelled** dataset, and it wires the
semantic harness's Jev predictor to the real ``SdkTransport``; every call is recorded in the
artefact next to the label it was compared with.

Two limitations the artefact states rather than hides:

* there is no live **DeepSeek** baseline predictor yet, so the A–E comparison measures Jev against
  the harness's non-Jev behaviour, not against DeepSeek;
* a live ``Score`` answer is a decimal on the definition's scale and is discretised by rounding to
  the nearest declared level, which is the metric's comparison, not a calibrated boundary.

Arms: ``--arm A|B|C|D|E`` (the historical nesting), ``--arm M-EXTRACT|M-ENTITY|
M-CONSISTENCY|M-CITATION|M-CAPABILITY|M-TOOL`` (the six structured-enhancement
component arms), ``--arm all`` (A–E), or ``--arm all-components`` (the six component
arms).

**A component arm reads both datasets, because no single one covers all six.** The primary
dataset labels the citation definitions (``source.supports_claim.v1`` 42 samples,
``source.select_span.v1`` 16) and none of the four module-specific families; the companion
dataset labels extraction / entity / consistency / capability / tool (7 each) and no citation
sample at all. Run against either file alone, five of the six arms — or the sixth — print a
page of ``INSUFFICIENT_SAMPLES`` and nothing else, which looks like a result and is not one.
So component arms default to the union, each metric keeps its own population (metrics are
computed per decision key, so the union cannot mix them), and the artefact records which
dataset supplied each metric. A component run in which **no** metric has a sample is refused
rather than written. The A–E arms are untouched: they still read exactly ``--dataset``.

Nothing here can cost money without the explicit ``--allow-billable`` flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.evaluation.jev_deepseek_baseline import (  # noqa: E402 -- after sys.path bootstrap
    deepseek_baseline_predictor,
    memoise_predictor,
)
from app.evaluation.jev_semantic_ablation import (  # noqa: E402 -- after sys.path bootstrap
    ARM_NAMES,
    COMPONENT_ARM_NAMES,
    INSUFFICIENT_SAMPLES,
    FakeJevTransport,
    compare_jev_arms,
    component_arm_metrics,
    deterministic_fake_jev_predictor,
    live_jev_predictor,
    load_jev_dataset,
    run_jev_semantic_ablation,
)
from app.evaluation.provider_safety import validate_deepseek_base_url  # noqa: E402
from app.jev.gateway import SdkTransport  # noqa: E402 -- after sys.path bootstrap

DATASET_PATH = ROOT / "benchmarks" / "jev-judgments.dataset.json"
# The primary dataset's frozen split manifest has its own name (the companion dataset's is
# `<stem>.split.json`); both are recorded as provenance so a reader can tie a run to the
# exact split a temperature was fitted against.
PRIMARY_SPLIT_PATH = ROOT / "benchmarks" / "jev-calibration.split.json"
# The companion dataset added in round 31 for the definitions the primary one does not
# label. A component arm needs both; see the module docstring.
MODULE_DATASET_PATH = ROOT / "benchmarks" / "jev-module-judgments.dataset.json"
DEFAULT_OUT = ROOT / "work" / "current-change" / "jev-ablation-offline.json"


def _dataset_provenance(path: Path, payload: dict) -> dict[str, Any]:
    """Where a dataset's samples came from, and which frozen split pins it.

    The datasets do not carry their own content hash — the split manifests do — so the
    manifest is looked up by the same naming rule the split builder uses, with the primary
    dataset's differently-named manifest as the one documented exception. A missing manifest
    is recorded as ``None`` rather than as an empty string that reads like a value.
    """

    declared = str(payload.get("content_hash") or "")
    # `X.dataset.json` -> `X.split.json`: `with_suffix` would replace only the final `.json`
    # and look for `X.dataset.split.json`, which does not exist.
    suffix = ".dataset.json"
    name = path.name
    manifest_path = (
        path.with_name(name[: -len(suffix)] + ".split.json")
        if name.endswith(suffix)
        else path.with_suffix(".split.json")
    )
    if path == DATASET_PATH:
        manifest_path = PRIMARY_SPLIT_PATH
    manifest_hash: str | None = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        manifest_hash = str(manifest.get("content_hash") or "") or None
    return {
        "path": str(path),
        "status": str(payload.get("dataset_status") or ""),
        "samples": len(payload.get("samples") or []),
        "dataset_content_hash": declared or None,
        "split_manifest": str(manifest_path) if manifest_hash else None,
        "split_content_hash": manifest_hash,
    }


def _write_json_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _merge_datasets(primary: dict, companion: dict, companion_path: Path) -> dict:
    """Concatenate two validated datasets so every component metric has its population.

    Each metric is computed from the samples carrying *its* decision key, so merging cannot
    mix populations — but the merged payload must still say where its samples came from, or
    a later reader cannot tell a 42-sample metric from a 7-sample one. Sample ids are
    checked for collisions rather than assumed unique.
    """

    primary_samples = list(primary.get("samples") or [])
    companion_samples = list(companion.get("samples") or [])
    seen = {str(sample.get("sample_id")) for sample in primary_samples}
    collisions = sorted(
        str(sample.get("sample_id"))
        for sample in companion_samples
        if str(sample.get("sample_id")) in seen
    )
    if collisions:
        raise ValueError(f"the two datasets share sample ids: {collisions[:5]}")
    merged = dict(primary)
    merged["samples"] = [*primary_samples, *companion_samples]
    merged["dataset_status"] = (
        f"{primary.get('dataset_status')}+{companion.get('dataset_status')}"
    )
    merged["merged_datasets"] = [
        {"path": str(companion_path), "samples": len(companion_samples)},
    ]
    return merged


def _metric_sources(datasets: list[tuple[Path, dict]], samples: list) -> dict[str, str]:
    """Which dataset labels each decision key, for the artefact's per-metric record."""
    sources: dict[str, str] = {}
    for path, payload in datasets:
        for sample in payload.get("samples") or []:
            sources.setdefault(str(sample.get("definition_id")), str(path))
    return {key: value for key, value in sources.items() if key in {
        str(sample.get("definition_id")) for sample in samples
    }}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--arm",
        choices=[*ARM_NAMES, *COMPONENT_ARM_NAMES, "all", "all-components"],
        default="all",
        help=(
            "Which arm(s) to run: A–E (the historical nesting), the six component arms "
            "(M-EXTRACT/M-ENTITY/M-CONSISTENCY/M-CITATION/M-CAPABILITY/M-TOOL), 'all' "
            "for the A–E arms, or 'all-components' for the six component arms."
        ),
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument(
        "--module-dataset",
        type=Path,
        default=MODULE_DATASET_PATH,
        help=(
            "The companion dataset a component arm also reads: it labels the module-specific "
            "families the primary dataset does not (extraction / entity / consistency / "
            "capability / tool), while the primary labels the citation metrics."
        ),
    )
    parser.add_argument(
        "--no-module-dataset",
        action="store_true",
        help=(
            "Read --dataset alone even for a component arm. The run is refused if that leaves "
            "every metric of the arm without a sample, so a metric-free table can never be "
            "written as a result."
        ),
    )
    parser.add_argument("--transport", choices=["fake", "live"], default="fake")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-billable", action="store_true")
    parser.add_argument(
        "--deepseek-baseline",
        action="store_true",
        help=(
            "Answer the non-Jev side of every arm with live DeepSeek, so the comparison measures "
            "Jev against a real baseline instead of against abstention. Requires a live run."
        ),
    )
    parser.add_argument("--deepseek-model", default="deepseek-flash")
    parser.add_argument("--deepseek-base-url", default="https://api.deepseek.com")
    parser.add_argument("--deepseek-timeout", type=float, default=60.0)
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


def _deepseek_baseline(args: argparse.Namespace) -> tuple[Any, list[dict]]:
    """Build the live DeepSeek baseline predictor, or (None, []) when it was not requested."""
    if not args.deepseek_baseline:
        return None, []
    import httpx

    api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
    base_url = validate_deepseek_base_url(args.deepseek_base_url)
    client = httpx.Client(
        timeout=httpx.Timeout(args.deepseek_timeout, connect=12), follow_redirects=False
    )

    def transport(endpoint: str, payload: dict) -> dict:
        response = client.post(
            endpoint, headers={"Authorization": "Bearer " + api_key}, json=payload
        )
        if response.status_code != 200:
            raise RuntimeError(f"PROVIDER_HTTP_{response.status_code}")
        return response.json()

    calls: list[dict] = []
    predictor = deepseek_baseline_predictor(
        transport,
        base_url=base_url,
        model=args.deepseek_model,
        calls=calls,
    )
    # The baseline answers each sample once and every arm sees that same answer; without this the
    # arms are not a controlled difference. See `memoise_predictor` for why.
    stats: dict[str, int] = {}
    memoised = memoise_predictor(predictor, stats=stats)
    memoised.cache_stats = stats  # type: ignore[attr-defined]
    return memoised, calls


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
    component = summary.get("component")
    if component:
        for name, metric in component.get("metrics", {}).items():
            if metric.get("status") == INSUFFICIENT_SAMPLES:
                print(f"    {name}=INSUFFICIENT_SAMPLES ({metric.get('samples', 0)} samples)")
            else:
                print(
                    f"    {name}={_fmt(metric.get('value'))} "
                    f"(status={metric.get('status')}, samples={metric.get('samples')})"
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

    dataset = None
    datasets: list[tuple[Path, dict]] = []
    try:
        dataset = load_jev_dataset(args.dataset)
        datasets.append((args.dataset, dataset))
        components_requested = args.arm == "all-components" or args.arm in COMPONENT_ARM_NAMES
        if (
            components_requested
            and not args.no_module_dataset
            and args.module_dataset != args.dataset
        ):
            companion = load_jev_dataset(args.module_dataset)
            datasets.append((args.module_dataset, companion))
            dataset = _merge_datasets(dataset, companion, args.module_dataset)
    except ValueError as error:
        print(f"Ablation preflight failed: {error}")
        return 2

    baseline_predictor = None
    baseline_calls: list[dict] = []
    if args.transport == "live":
        baseline_predictor, baseline_calls = _deepseek_baseline(args)

    if args.arm == "all":
        arms = list(ARM_NAMES)
    elif args.arm == "all-components":
        arms = list(COMPONENT_ARM_NAMES)
    else:
        arms = [args.arm]
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
            # The live path, which used to be a refusal: the semantic harness has an injectable
            # predictor interface and the Jev side of it is now wired to the real transport. The
            # DeepSeek baseline predictor still does not exist, so arm A runs against the harness's
            # own non-Jev behaviour and the artefact records that as a limitation rather than
            # pretending the comparison is Jev-versus-DeepSeek.
            live_calls: list[dict] = []
            transport = SdkTransport()
            summary = run_jev_semantic_ablation(
                dataset,
                arm,
                transport=transport,
                jev_predictor=live_jev_predictor(transport, calls=live_calls),
                deepseek_predictor=baseline_predictor,
            )
            summary["live_calls"] = live_calls
            summary["live_call_count"] = len(live_calls)
        arm_summaries.append(summary)

    runs = {summary["arm"]: summary for summary in arm_summaries}
    comparison = compare_jev_arms(runs)

    # A component arm that measured nothing is not a result. Before this check the runner
    # happily printed a table of zeros and INSUFFICIENT_SAMPLES for five of the six arms —
    # the numbers it did print came from the one arm whose definitions the primary dataset
    # happens to label, so the run looked complete and measured almost nothing.
    metric_sources = _metric_sources(datasets, dataset.get("samples") or [])
    empty_components = []
    for summary in arm_summaries:
        arm = str(summary.get("arm"))
        if arm not in COMPONENT_ARM_NAMES:
            continue
        component = summary.get("component") or {}
        summary["metric_sources"] = {
            metric: metric_sources.get(key)
            for metric, key in component_arm_metrics(arm)
        }
        if component.get("metrics") and all(
            metric.get("status") == INSUFFICIENT_SAMPLES
            for metric in component["metrics"].values()
        ):
            empty_components.append(arm)

    print(f"Jev ablation: transport={args.transport} arms={','.join(arms)}")
    for summary in arm_summaries:
        _summarize_arm(summary)
    print(f"comparison verdict={comparison['verdict']}")

    if empty_components:
        print(
            "Refusing to write: every metric of "
            + ", ".join(empty_components)
            + " has no labelled sample in "
            + ", ".join(str(path) for path, _ in datasets)
            + ". A component arm needs the dataset that labels its definitions — see the "
            "module docstring for which one that is."
        )
        return 4

    effective_transports = sorted({summary.get("transport") for summary in arm_summaries})
    expected_transport = "deterministic_fake" if args.transport == "fake" else args.transport
    if effective_transports != [expected_transport]:
        print(
            "Refusing to write: the run used "
            f"{effective_transports} but the artefact would claim {expected_transport!r}."
        )
        return 3

    if args.transport == "fake" and args.deepseek_baseline:
        print("Refusing: --deepseek-baseline only applies to a live run.")
        return 2
    payload = {
        "transport": args.transport,
        "transport_used": effective_transports[0],
        "dataset_status": dataset.get("dataset_status"),
        "dataset_path": str(args.dataset),
        # Every dataset this run actually read, and how many samples each contributed: a
        # component arm reads two, and a reader must be able to see which one a metric's
        # population came from without reproducing the run.
        "dataset_sources": [
            _dataset_provenance(path, payload_) for path, payload_ in datasets
        ],
        "allow_billable": args.allow_billable,
        "baseline": {
            "injected": baseline_predictor is not None,
            "provider": "deepseek" if baseline_predictor is not None else None,
            "model": args.deepseek_model if baseline_predictor is not None else None,
            "calls": len(baseline_calls),
            "answered_once_per_sample": baseline_predictor is not None,
            "cache_reuses_across_arms": getattr(
                getattr(baseline_predictor, "cache_stats", None), "get", lambda *_: 0
            )("count", 0),
            "call_log": baseline_calls,
            "note": (
                ""
                if baseline_predictor is not None
                else "no production predictor injected: arm A abstains, so the comparison verdict "
                "is NOT_INTERPRETABLE by the harness's own rule"
            ),
        },
        "comparison": comparison,
        "arms": arm_summaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomically(args.out, payload)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
