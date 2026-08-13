from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BillableRunNotAuthorized(RuntimeError):
    """Raised before any provider call unless billing is explicitly authorized."""


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

    @classmethod
    def minimal(cls, case_id: str, category: str, prompt: str) -> BenchmarkCase:
        return cls(case_id, category, prompt, "auto", (), (), False, ())

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

    @classmethod
    def from_response(
        cls,
        case: BenchmarkCase,
        response_text: str,
        tool_called: bool,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
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
        )


def load_benchmark_cases(path: Path) -> list[BenchmarkCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Benchmark dataset must be a JSON array.")
    cases = [BenchmarkCase.from_mapping(item) for item in payload]
    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Benchmark case IDs must be unique.")
    return cases


def run_benchmark(
    cases: Iterable[BenchmarkCase],
    provider: Callable[[BenchmarkCase], BenchmarkResult],
    *,
    allow_billable: bool,
) -> list[BenchmarkResult]:
    if not allow_billable:
        raise BillableRunNotAuthorized(
            "Refusing provider calls without explicit --allow-billable authorization."
        )
    return [provider(case) for case in cases]


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
    return {
        "provider": provider,
        "model": model,
        "case_count": total,
        "automated_pass_rate": passed / total if total else 0.0,
        "average_latency_ms": (
            sum(result.latency_ms for result in results) / total if total else 0.0
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
