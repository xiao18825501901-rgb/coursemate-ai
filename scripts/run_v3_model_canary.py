"""Run the bounded CourseMate V3 structured canary against qwen3.8-max.

The script is fail-closed: it performs no provider call without an explicit billable
opt-in, verified prices, a whole-run cost ceiling, a provider-call ceiling, an exact
Model Studio endpoint, and a bounded local synthetic image. It never retries or resumes
automatically. Partial paid evidence is checkpointed after every completed call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICE = ROOT / "services" / "rag-api"
sys.path.insert(0, str(RAG_SERVICE))

from app.config import Settings  # noqa: E402
from app.evaluation.model_benchmark import calculate_cost_ceiling  # noqa: E402
from app.evaluation.provider_safety import validate_model_studio_base_url  # noqa: E402
from app.evaluation.v3_model_canary import (  # noqa: E402
    call_input_token_ceilings,
    detect_image_media_type,
    load_v3_teaching_cases,
    run_image_problem_case,
    run_teaching_case,
)
from app.learning.provider import (  # noqa: E402
    LearningProvider,
    ProviderCallFailure,
)

MODEL = "qwen3.8-max"
DEFAULT_MAX_IMAGE_BYTES = 2 * 1024 * 1024
DATASET = ROOT / "benchmarks" / "v3-teaching-canary-cases.json"


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--max-image-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    parser.add_argument("--max-output-tokens", type=int, default=4_000)
    parser.add_argument("--max-provider-calls", type=int, required=True)
    parser.add_argument("--input-price-per-million", type=float, required=True)
    parser.add_argument("--output-price-per-million", type=float, required=True)
    parser.add_argument("--max-cost", type=float, required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-synthetic-image", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--allow-billable", action="store_true")
    return parser.parse_args()


def _artifact(
    *,
    base_url: str,
    selected_case_ids: list[str],
    image_content: bytes,
    image_media_type: str,
    provider_call_count: int,
    currency: str,
    input_price_per_million: float,
    output_price_per_million: float,
    max_cost: float,
    cost_ceiling: float,
) -> dict[str, Any]:
    endpoint_label = {
        "dashscope.aliyuncs.com": "ENDPOINT_CN",
        "dashscope-intl.aliyuncs.com": "ENDPOINT_INTL",
        "dashscope-us.aliyuncs.com": "ENDPOINT_US",
        "cn-hongkong.dashscope.aliyuncs.com": "ENDPOINT_HK",
    }.get(urlsplit(base_url).hostname or "", "ENDPOINT_WORKSPACE")
    return {
        "artifact_version": "v3-live-canary-v1",
        "status": "RUNNING",
        "live_verification": "NOT_VERIFIED_UNTIL_CALLS_AND_HUMAN_REVIEW_COMPLETE",
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provider": "ALIBABA_MODEL_STUDIO_COMPATIBLE",
        "model": MODEL,
        "protocol": "responses",
        "endpoint_label": endpoint_label,
        "dataset": {
            "path": "benchmarks/v3-teaching-canary-cases.json",
            "sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        },
        "selected_case_ids": selected_case_ids,
        "image": {
            "media_type": image_media_type,
            "sha256": hashlib.sha256(image_content).hexdigest(),
            "byte_size": len(image_content),
        },
        "authorized_provider_calls": provider_call_count,
        "currency": currency,
        "input_price_per_million": input_price_per_million,
        "output_price_per_million": output_price_per_million,
        "price_basis": "OWNER_SUPPLIED_AT_RUN_TIME",
        "approved_max_cost": max_cost,
        "preflight_cost_ceiling": cost_ceiling,
        "actual_estimated_cost": 0.0,
        "calls": [],
        "teaching_results": [],
        "image_result": None,
        "manual_review_status": "REQUIRED",
        "failure_class": None,
    }


def _actual_cost(
    calls: list[dict[str, Any]],
    *,
    input_price: float,
    output_price: float,
) -> float:
    input_tokens = sum(int(call["run"].get("input_tokens", 0)) for call in calls)
    output_tokens = sum(int(call["run"].get("output_tokens", 0)) for call in calls)
    return round(
        (input_tokens * input_price + output_tokens * output_price) / 1_000_000,
        8,
    )


def main() -> int:
    args = parse_args()
    if not args.preflight_only and not args.allow_billable:
        print("Refusing provider calls: pass --allow-billable after approving model charges.")
        return 2
    if not args.preflight_only and not args.confirm_synthetic_image:
        print(
            "Refusing provider calls: pass --confirm-synthetic-image only for a "
            "non-private benchmark image."
        )
        return 2
    if args.max_provider_calls <= 0:
        print("--max-provider-calls must be positive.")
        return 2
    if not 500 <= args.max_output_tokens <= 8_000:
        print("--max-output-tokens must be between 500 and 8000.")
        return 2
    if args.max_image_bytes <= 0:
        print("--max-image-bytes must be positive.")
        return 2
    if not math.isfinite(args.max_cost) or args.max_cost <= 0:
        print("--max-cost must be finite and positive.")
        return 2
    if re.fullmatch(r"[A-Z]{3}", args.currency) is None:
        print("--currency must be a three-letter uppercase ISO 4217 code.")
        return 2
    try:
        base_url = validate_model_studio_base_url(args.base_url)
    except ValueError as error:
        print(str(error))
        return 2
    try:
        cases = load_v3_teaching_cases(DATASET)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Invalid V3 canary dataset: {type(error).__name__}.")
        return 2
    if args.case_id:
        requested = set(args.case_id)
        known = {case.id for case in cases}
        if not requested <= known:
            print("Unknown --case-id; no provider call was made.")
            return 2
        cases = [case for case in cases if case.id in requested]
    if not cases:
        print("No V3 teaching canary cases selected.")
        return 2
    try:
        image_content = args.image.read_bytes()
    except OSError:
        print("The synthetic canary image could not be read.")
        return 2
    image_media_type = detect_image_media_type(image_content)
    if image_media_type is None:
        print("The canary image must be a local PNG or JPEG.")
        return 2
    if not image_content or len(image_content) > args.max_image_bytes:
        print("The canary image is empty or exceeds --max-image-bytes.")
        return 2
    provider_call_count = len(cases) * 2 + 1
    if provider_call_count > args.max_provider_calls:
        print(
            f"Refusing provider calls: selection requires {provider_call_count} provider calls "
            f"but only {args.max_provider_calls} were authorized."
        )
        return 2
    try:
        ceilings = call_input_token_ceilings(
            cases,
            max_output_tokens=args.max_output_tokens,
            image_content=image_content,
            image_media_type=image_media_type,
        )
        cost_ceiling = calculate_cost_ceiling(
            ceilings,
            max_output_tokens_per_case=args.max_output_tokens,
            input_price_per_million=args.input_price_per_million,
            output_price_per_million=args.output_price_per_million,
        )
    except ValueError as error:
        print(f"Invalid V3 canary budget configuration: {error}")
        return 2
    if cost_ceiling > args.max_cost:
        print(
            f"Refusing provider calls: conservative {args.currency} cost ceiling "
            f"{cost_ceiling:.8f} exceeds approved maximum {args.max_cost:.8f}."
        )
        return 2
    print(
        f"V3 canary preflight: {provider_call_count} provider calls, conservative "
        f"{args.currency} ceiling {cost_ceiling:.8f}, model {MODEL}."
    )
    if args.preflight_only:
        return 0
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Missing credential environment variable: {args.api_key_env}")
        return 2
    partial_path = args.output.with_name(f".{args.output.name}.partial")
    checkpoint_path = args.output.with_name(f".{args.output.name}.checkpoint.json")
    if args.output.exists() or partial_path.exists() or checkpoint_path.exists():
        print("Refusing to overwrite an existing V3 canary output or checkpoint.")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        app_env="production",
        rag_provider_mode="openai",
        v3_enabled=True,
        v3_model=MODEL,
        v3_model_api_key=api_key,
        v3_model_base_url=base_url,
        v3_max_output_tokens=args.max_output_tokens,
    )
    provider = LearningProvider(settings)
    artifact = _artifact(
        base_url=base_url,
        selected_case_ids=[case.id for case in cases],
        image_content=image_content,
        image_media_type=image_media_type,
        provider_call_count=provider_call_count,
        currency=args.currency,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
        max_cost=args.max_cost,
        cost_ceiling=cost_ceiling,
    )
    active_case = "unstarted"

    def checkpoint(role: str, output: Any, run: dict[str, Any]) -> None:
        artifact["calls"].append(
            {
                "case_id": active_case,
                "role": role,
                "run": run,
                "structured_output": output.model_dump(),
            }
        )
        artifact["actual_estimated_cost"] = _actual_cost(
            artifact["calls"],
            input_price=args.input_price_per_million,
            output_price=args.output_price_per_million,
        )
        _write_json_atomically(checkpoint_path, artifact)

    try:
        for case in cases:
            active_case = case.id
            result = run_teaching_case(case, provider, on_call=checkpoint)
            artifact["teaching_results"].append(result)
            _write_json_atomically(checkpoint_path, artifact)
        active_case = "image-problem"
        artifact["image_result"] = run_image_problem_case(
            provider,
            image_content=image_content,
            image_media_type=image_media_type,
            on_call=checkpoint,
        )
        _write_json_atomically(checkpoint_path, artifact)
    except ProviderCallFailure as error:
        artifact["calls"].append(
            {"case_id": active_case, "role": error.run["role"], "run": error.run}
        )
        artifact["status"] = "FAILED_PROVIDER_CALL"
        artifact["failure_class"] = error.run.get("error_class", "UNKNOWN")
        artifact["actual_estimated_cost"] = _actual_cost(
            artifact["calls"],
            input_price=args.input_price_per_million,
            output_price=args.output_price_per_million,
        )
        _write_json_atomically(checkpoint_path, artifact)
        print(
            "V3 canary stopped after a provider failure; no retry was attempted. "
            "Preserve the checkpoint.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, OSError) as error:
        artifact["status"] = "FAILED_CONTRACT_VALIDATION"
        artifact["failure_class"] = type(error).__name__
        _write_json_atomically(checkpoint_path, artifact)
        print(
            "V3 canary stopped after local contract validation; no retry was attempted. "
            "Preserve the checkpoint.",
            file=sys.stderr,
        )
        return 1
    automated_pass = all(
        result["automated_pass"] for result in artifact["teaching_results"]
    ) and bool(artifact["image_result"]["automated_pass"])
    artifact["status"] = (
        "LIVE_CALLS_COMPLETED_MANUAL_REVIEW_REQUIRED"
        if automated_pass
        else "LIVE_CALLS_COMPLETED_AUTOMATED_CHECK_FAILED"
    )
    artifact["live_verification"] = (
        "PENDING_HUMAN_QUALITY_REVIEW" if automated_pass else "NOT_VERIFIED"
    )
    artifact["finished_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_json_atomically(args.output, artifact)
    checkpoint_path.unlink()
    print(
        f"Wrote {len(artifact['calls'])} paid-call records. Human quality review remains required."
    )
    return 0 if automated_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
