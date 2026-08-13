import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.model_benchmark import (
    BenchmarkCase,
    BenchmarkResult,
    BillableRunNotAuthorized,
    consume_text_stream,
    load_benchmark_cases,
    run_benchmark,
    summarize_results,
)

DATASET = Path(__file__).parents[3] / "benchmarks" / "tutor-model-cases.json"


def test_v2_benchmark_dataset_has_50_cases_and_required_coverage() -> None:
    cases = load_benchmark_cases(DATASET)

    assert len(cases) == 50
    assert {
        "chinese_tutoring",
        "english_tutoring",
        "grounded_qa",
        "exact_locator",
        "multi_turn",
        "general_chat",
        "course_isolation",
        "private_course",
        "prompt_customization",
        "agent_tools",
    }.issubset({case.category for case in cases})
    assert {
        "language",
        "rag",
        "exact_locator",
        "examples",
        "multi_turn",
        "general_conversation",
        "course_isolation",
        "private_course",
        "multi_user_security",
        "prompt_customization",
    }.issubset({label for case in cases for label in case.coverage})


def test_benchmark_refuses_network_calls_without_explicit_billable_opt_in() -> None:
    called = False

    def provider(case: BenchmarkCase) -> BenchmarkResult:
        nonlocal called
        called = True
        return BenchmarkResult.from_response(case, "unused", False, 1.0, 1, 1)

    with pytest.raises(BillableRunNotAuthorized):
        run_benchmark(
            [BenchmarkCase.minimal("case-1", "general_chat", "hello")],
            provider,
            allow_billable=False,
        )

    assert called is False


def test_automated_scoring_and_summary_do_not_include_credentials() -> None:
    case = BenchmarkCase(
        id="zh-1",
        category="chinese_tutoring",
        prompt="什么是核心点？",
        expected_language="zh-CN",
        must_contain_any=("核心点",),
        must_not_contain=("资料中没有",),
        expects_tool_call=False,
    )

    result = BenchmarkResult.from_response(
        case,
        "核心点需要在邻域内达到最小样本数。",
        False,
        123.0,
        12,
        18,
    )
    summary = summarize_results([result], provider="candidate-a", model="model-a")
    rendered = json.dumps(summary, ensure_ascii=False)

    assert result.automated_pass is True
    assert summary["automated_pass_rate"] == 1.0
    assert "api_key" not in rendered.casefold()
    assert "secret" not in rendered.casefold()


def test_tool_case_requires_a_function_call() -> None:
    case = BenchmarkCase(
        id="tool-1",
        category="agent_tools",
        prompt="Create a task to revise clustering.",
        expected_language="en",
        must_contain_any=(),
        must_not_contain=(),
        expects_tool_call=True,
    )

    without_call = BenchmarkResult.from_response(case, "Done.", False, 10, 3, 2)
    with_call = BenchmarkResult.from_response(case, "", True, 10, 3, 2)

    assert without_call.automated_pass is False
    assert with_call.automated_pass is True


def test_stream_sampling_records_ttft_text_and_usage() -> None:
    times = iter([10.12, 10.40])
    events = [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.output_text.delta", delta="Hello "),
        SimpleNamespace(type="response.output_text.delta", delta="student"),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=11, output_tokens=2)
            ),
        ),
    ]

    sample = consume_text_stream(events, started_at=10.0, clock=lambda: next(times))

    assert sample.text == "Hello student"
    assert sample.time_to_first_token_ms == 120.0
    assert sample.latency_ms == 400.0
    assert sample.input_tokens == 11
    assert sample.output_tokens == 2


def test_summary_reports_latency_and_streaming_percentiles() -> None:
    case = BenchmarkCase.minimal("stream-1", "general_chat", "hello")
    first = BenchmarkResult.from_response(
        case, "hello", False, 100.0, 1, 1,
        streaming_tested=True, streaming_supported=True, time_to_first_token_ms=20.0,
    )
    second = BenchmarkResult.from_response(
        case, "hello", False, 300.0, 1, 1,
        streaming_tested=True, streaming_supported=True, time_to_first_token_ms=60.0,
    )

    summary = summarize_results([first, second], provider="candidate", model="model")

    assert summary["latency_ms"]["p50"] == 200.0
    assert summary["latency_ms"]["p95"] == 290.0
    assert summary["time_to_first_token_ms"]["p50"] == 40.0
    assert summary["streaming_support_rate"] == 1.0
