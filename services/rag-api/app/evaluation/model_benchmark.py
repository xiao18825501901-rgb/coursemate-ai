from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BillableRunNotAuthorized(RuntimeError):
    """Raised before any provider call unless billing is explicitly authorized."""


def conservative_input_token_ceiling(
    instructions: str,
    prompt: str,
    *,
    protocol_overhead_tokens: int,
) -> int:
    """Return a tokenizer-independent upper bound using one UTF-8 byte per token."""
    if protocol_overhead_tokens < 0:
        raise ValueError("Protocol overhead tokens cannot be negative.")
    return (
        len(instructions.encode()) + len(prompt.encode()) + protocol_overhead_tokens
    )


def calculate_cost_ceiling(
    input_token_ceilings: Iterable[int],
    *,
    max_output_tokens_per_case: int,
    input_price_per_million: float,
    output_price_per_million: float,
) -> float:
    """Calculate the maximum authorized cost before constructing a provider client."""
    ceilings = list(input_token_ceilings)
    if not ceilings or any(value < 0 for value in ceilings):
        raise ValueError("Input token ceilings must be non-negative and non-empty.")
    if max_output_tokens_per_case <= 0:
        raise ValueError("Maximum output tokens per case must be positive.")
    if not math.isfinite(input_price_per_million) or not math.isfinite(
        output_price_per_million
    ):
        raise ValueError("Benchmark prices must be finite.")
    if input_price_per_million < 0 or output_price_per_million < 0:
        raise ValueError("Benchmark prices cannot be negative.")
    if input_price_per_million == 0 and output_price_per_million == 0:
        raise ValueError("Set at least one benchmark price before authorizing billable calls.")
    total_output_ceiling = len(ceilings) * max_output_tokens_per_case
    cost = (
        sum(ceilings) * input_price_per_million
        + total_output_ceiling * output_price_per_million
    ) / 1_000_000
    return round(cost, 8)


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    category: str
    prompt: str
    expected_language: str
    must_contain_any: tuple[str, ...]
    must_not_contain: tuple[str, ...]
    expects_tool_call: bool
    coverage: tuple[str, ...] = ()
    expected_tool_sequence: tuple[str, ...] = ()

    @classmethod
    def minimal(cls, case_id: str, category: str, prompt: str) -> BenchmarkCase:
        return cls(case_id, category, prompt, "auto", (), (), False, (), ())

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> BenchmarkCase:
        return cls(
            id=str(value["id"]),
            category=str(value["category"]),
            prompt=str(value["prompt"]),
            expected_language=str(value.get("expected_language", "auto")),
            must_contain_any=tuple(str(item) for item in value.get("must_contain_any", [])),
            must_not_contain=tuple(str(item) for item in value.get("must_not_contain", [])),
            expects_tool_call=bool(value.get("expects_tool_call", False)),
            coverage=tuple(str(item) for item in value.get("coverage", [])),
            expected_tool_sequence=tuple(
                str(item) for item in value.get("expected_tool_sequence", [])
            ),
        )


def _looks_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text))


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    category: str
    response_text: str
    tool_called: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int
    automated_pass: bool
    checks: dict[str, bool]
    streaming_tested: bool = False
    streaming_supported: bool = False
    time_to_first_token_ms: float | None = None
    tool_sequence: tuple[str, ...] = ()
    tool_schema_valid: bool = False
    call_id_replayed: bool = False
    final_response_received: bool = False

    @classmethod
    def from_response(
        cls,
        case: BenchmarkCase,
        response_text: str,
        tool_called: bool,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        *,
        streaming_tested: bool = False,
        streaming_supported: bool = False,
        time_to_first_token_ms: float | None = None,
        tool_sequence: tuple[str, ...] = (),
        tool_schema_valid: bool = False,
        call_id_replayed: bool = False,
        final_response_received: bool = False,
    ) -> BenchmarkResult:
        folded = response_text.casefold()
        checks = {
            "has_output_or_tool": bool(response_text.strip()) or tool_called,
            "contains_expected_signal": not case.must_contain_any
            or any(token.casefold() in folded for token in case.must_contain_any),
            "avoids_forbidden_signal": all(
                token.casefold() not in folded for token in case.must_not_contain
            ),
            "language": case.expected_language not in {"zh-CN", "zh"}
            or _looks_chinese(response_text),
            "tool_call": not case.expects_tool_call or tool_called,
            "tool_sequence": not case.expects_tool_call
            or tool_sequence == case.expected_tool_sequence,
            "tool_schema": not case.expects_tool_call or tool_schema_valid,
            "call_id_replay": not case.expects_tool_call or call_id_replayed,
            "final_response": not case.expects_tool_call or final_response_received,
        }
        return cls(
            case_id=case.id,
            category=case.category,
            response_text=response_text,
            tool_called=tool_called,
            latency_ms=round(latency_ms, 3),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            automated_pass=all(checks.values()),
            checks=checks,
            streaming_tested=streaming_tested,
            streaming_supported=streaming_supported,
            time_to_first_token_ms=(
                round(time_to_first_token_ms, 3)
                if time_to_first_token_ms is not None
                else None
            ),
            tool_sequence=tool_sequence,
            tool_schema_valid=tool_schema_valid,
            call_id_replayed=call_id_replayed,
            final_response_received=final_response_received,
        )


@dataclass(frozen=True)
class StreamSample:
    text: str
    latency_ms: float
    time_to_first_token_ms: float | None
    input_tokens: int
    output_tokens: int


def consume_text_stream(
    events: Iterable[Any],
    *,
    started_at: float,
    clock: Callable[[], float],
) -> StreamSample:
    """Consume a Responses text stream and record transport-level timing evidence."""
    text_parts: list[str] = []
    first_token_at: float | None = None
    input_tokens = 0
    output_tokens = 0

    for event in events:
        event_type = getattr(event, "type", "")
        if event_type == "response.output_text.delta":
            if first_token_at is None:
                first_token_at = clock()
            text_parts.append(str(getattr(event, "delta", "")))
        elif event_type == "response.completed":
            usage = getattr(getattr(event, "response", None), "usage", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "input_tokens", 0))
                output_tokens = int(getattr(usage, "output_tokens", 0))
        elif event_type in {"error", "response.failed", "response.incomplete"}:
            raise RuntimeError(f"Model stream ended with {event_type}.")

    finished_at = clock()
    return StreamSample(
        text="".join(text_parts),
        latency_ms=round((finished_at - started_at) * 1_000, 3),
        time_to_first_token_ms=(
            round((first_token_at - started_at) * 1_000, 3)
            if first_token_at is not None
            else None
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def load_benchmark_cases(path: Path) -> list[BenchmarkCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Benchmark dataset must be a JSON array.")
    cases = [BenchmarkCase.from_mapping(item) for item in payload]
    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Benchmark case IDs must be unique.")
    if any(case.expects_tool_call != bool(case.expected_tool_sequence) for case in cases):
        raise ValueError(
            "Tool cases must define a non-empty expected_tool_sequence, and text cases must not."
        )
    return cases


def run_benchmark(
    cases: Iterable[BenchmarkCase],
    provider: Callable[[BenchmarkCase], BenchmarkResult],
    *,
    allow_billable: bool,
    on_result: Callable[[list[BenchmarkResult]], None] | None = None,
) -> list[BenchmarkResult]:
    if not allow_billable:
        raise BillableRunNotAuthorized(
            "Refusing provider calls without explicit --allow-billable authorization."
        )
    results: list[BenchmarkResult] = []
    for case in cases:
        results.append(provider(case))
        if on_result is not None:
            on_result(list(results))
    return results


def summarize_results(
    results: list[BenchmarkResult],
    *,
    provider: str,
    model: str,
    input_price_per_million: float = 0.0,
    output_price_per_million: float = 0.0,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(result.automated_pass for result in results)
    by_category = Counter(result.category for result in results)
    category_passes = Counter(
        result.category for result in results if result.automated_pass
    )
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    estimated_cost = (
        input_tokens * input_price_per_million
        + output_tokens * output_price_per_million
    ) / 1_000_000
    latencies = [result.latency_ms for result in results]
    time_to_first_token = [
        result.time_to_first_token_ms
        for result in results
        if result.time_to_first_token_ms is not None
    ]
    streaming_tested = sum(result.streaming_tested for result in results)
    streaming_supported = sum(
        result.streaming_supported for result in results if result.streaming_tested
    )
    return {
        "provider": provider,
        "model": model,
        "case_count": total,
        "automated_pass_rate": passed / total if total else 0.0,
        "average_latency_ms": (
            sum(result.latency_ms for result in results) / total if total else 0.0
        ),
        "latency_ms": _metric_summary(latencies),
        "time_to_first_token_ms": _metric_summary(time_to_first_token),
        "streaming_support_rate": (
            streaming_supported / streaming_tested if streaming_tested else None
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": round(estimated_cost, 8),
        "category_pass_rates": {
            category: category_passes[category] / count
            for category, count in sorted(by_category.items())
        },
        "manual_review_status": "required",
        "manual_rubric": [
            "retrieval_relevance",
            "source_correctness",
            "citation_correctness",
            "teaching_depth",
            "step_by_step_quality",
            "chinese_quality",
            "follow_up_coherence",
            "hallucination",
            "instruction_adherence",
        ],
        "results": [asdict(result) for result in results],
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _metric_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": round(sum(values) / len(values), 3) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }
