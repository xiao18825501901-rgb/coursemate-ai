import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.evaluation.agent_tool_benchmark import (
    MAX_AGENT_RESPONSE_ROUNDS,
    TASK_TOOLS,
    run_agent_tool_conversation,
    simulated_tool_output,
    validate_tool_arguments,
)
from app.evaluation.model_benchmark import (
    BenchmarkCase,
    BenchmarkResult,
    BillableRunNotAuthorized,
    calculate_cost_ceiling,
    conservative_input_token_ceiling,
    consume_text_stream,
    load_benchmark_cases,
    run_benchmark,
    summarize_results,
)
from app.evaluation.provider_safety import (
    validate_model_studio_base_url,
    validate_provider_base_url,
)

DATASET = Path(__file__).parents[3] / "benchmarks" / "tutor-model-cases.json"
RUNNER = Path(__file__).parents[3] / "scripts" / "run_model_benchmark.py"


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
    assert {
        case.id: case.expected_tool_sequence
        for case in cases
        if case.expects_tool_call
    } == {
        "tool-01": ("createTask",),
        "tool-02": ("searchTask",),
        "tool-03": ("searchTask", "completeTask"),
        "tool-04": ("searchTask", "updateTask"),
        "tool-05": ("searchTask", "deleteTask"),
    }


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


def test_benchmark_checkpoints_each_completed_case_before_provider_failure() -> None:
    cases = [
        BenchmarkCase.minimal("case-1", "general_chat", "hello"),
        BenchmarkCase.minimal("case-2", "general_chat", "hello again"),
    ]
    checkpoint_sizes: list[int] = []

    def provider(case: BenchmarkCase) -> BenchmarkResult:
        if case.id == "case-2":
            raise RuntimeError("provider failed")
        return BenchmarkResult.from_response(case, "hello", False, 1.0, 1, 1)

    with pytest.raises(RuntimeError, match="provider failed"):
        run_benchmark(
            cases,
            provider,
            allow_billable=True,
            on_result=lambda results: checkpoint_sizes.append(len(results)),
        )

    assert checkpoint_sizes == [1]


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


def test_tool_case_requires_expected_valid_replayed_sequence_and_final_response() -> None:
    case = BenchmarkCase(
        id="tool-1",
        category="agent_tools",
        prompt="Create a task to revise clustering.",
        expected_language="en",
        must_contain_any=(),
        must_not_contain=(),
        expects_tool_call=True,
        expected_tool_sequence=("createTask",),
    )

    without_call = BenchmarkResult.from_response(case, "Done.", False, 10, 3, 2)
    wrong_call = BenchmarkResult.from_response(
        case,
        "Done.",
        True,
        10,
        3,
        2,
        tool_sequence=("deleteTask",),
        tool_schema_valid=True,
        call_id_replayed=True,
        final_response_received=True,
    )
    valid_call = BenchmarkResult.from_response(
        case,
        "Created.",
        True,
        10,
        3,
        2,
        tool_sequence=("createTask",),
        tool_schema_valid=True,
        call_id_replayed=True,
        final_response_received=True,
    )

    assert without_call.automated_pass is False
    assert wrong_call.automated_pass is False
    assert valid_call.automated_pass is True


def test_agent_tool_contract_matches_production_shapes_and_rejects_bad_json() -> None:
    assert [tool["name"] for tool in TASK_TOOLS] == [
        "createTask",
        "searchTask",
        "updateTask",
        "completeTask",
        "deleteTask",
    ]
    assert {
        tool["name"]: tool["parameters"]["required"] for tool in TASK_TOOLS
    } == {
        "createTask": [
            "title",
            "notes",
            "courseId",
            "priority",
            "dueDate",
            "sourceCitation",
        ],
        "searchTask": ["query", "courseId", "status", "page", "pageSize"],
        "updateTask": [
            "taskId",
            "updateFields",
            "title",
            "notes",
            "courseId",
            "status",
            "priority",
            "dueDate",
        ],
        "completeTask": ["taskId"],
        "deleteTask": ["taskId"],
    }
    valid_search = {
        "query": "Review DBSCAN",
        "courseId": None,
        "status": None,
        "page": 1,
        "pageSize": 20,
    }
    assert validate_tool_arguments("searchTask", valid_search) is True
    assert validate_tool_arguments("searchTask", {**valid_search, "ownerUserId": "other"}) is False
    assert validate_tool_arguments("searchTask", {**valid_search, "page": "1"}) is False
    assert validate_tool_arguments("unknownTool", {}) is False


def test_agent_tool_simulator_is_content_safe_and_supports_multi_round_replay() -> None:
    result = simulated_tool_output("searchTask")
    rendered = json.dumps(result)

    assert result["ok"] is True
    assert result["data"]["items"][0]["id"] == "benchmark-task-1"
    assert "prompt" not in rendered.casefold()
    assert "course content" not in rendered.casefold()
    assert MAX_AGENT_RESPONSE_ROUNDS >= 3


def test_agent_tool_conversation_replays_exact_call_ids_and_collects_usage() -> None:
    responses = iter(
        [
            SimpleNamespace(
                output_text="",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        call_id="search-call-1",
                        name="searchTask",
                        arguments=json.dumps(
                            {
                                "query": "Review DBSCAN",
                                "courseId": None,
                                "status": None,
                                "page": 1,
                                "pageSize": 20,
                            }
                        ),
                    )
                ],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            ),
            SimpleNamespace(
                output_text="",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        call_id="complete-call-2",
                        name="completeTask",
                        arguments=json.dumps({"taskId": "benchmark-task-1"}),
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=5),
            ),
            SimpleNamespace(
                output_text="Completed Review DBSCAN.",
                output=[],
                usage=SimpleNamespace(input_tokens=25, output_tokens=4),
            ),
        ]
    )
    submitted_inputs: list[list[object]] = []

    def create_response(input_items: list[object]) -> object:
        submitted_inputs.append(input_items)
        return next(responses)

    sample = run_agent_tool_conversation("Complete Review DBSCAN", create_response)

    assert sample.tool_sequence == ("searchTask", "completeTask")
    assert sample.tool_schema_valid is True
    assert sample.call_id_replayed is True
    assert sample.final_response_received is True
    assert sample.input_tokens == 55
    assert sample.output_tokens == 14
    search_output = submitted_inputs[1][-1]
    complete_output = submitted_inputs[2][-1]
    assert isinstance(search_output, dict)
    assert isinstance(complete_output, dict)
    assert search_output["call_id"] == "search-call-1"
    assert complete_output["call_id"] == "complete-call-2"


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


def test_benchmark_cost_ceiling_is_conservative_and_requires_real_prices() -> None:
    chinese_request_ceiling = conservative_input_token_ceiling(
        "You are a tutor.", "请解释核心点。", protocol_overhead_tokens=128
    )
    assert chinese_request_ceiling >= 128 + len("请解释核心点。".encode())

    ceiling = calculate_cost_ceiling(
        [chinese_request_ceiling, 500],
        max_output_tokens_per_case=1_200,
        input_price_per_million=2.0,
        output_price_per_million=8.0,
    )
    expected = ((chinese_request_ceiling + 500) * 2.0 + 2_400 * 8.0) / 1_000_000
    assert ceiling == round(expected, 8)

    with pytest.raises(ValueError, match="at least one benchmark price"):
        calculate_cost_ceiling(
            [500],
            max_output_tokens_per_case=1_200,
            input_price_per_million=0.0,
            output_price_per_million=0.0,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/v1",
        "https://user:secret@provider.example/v1",
        "https://provider.example/v1?key=secret",
        "https://provider.example/v1#fragment",
        "https://[broken",
        "https://provider.example/\x00",
    ],
)
def test_provider_base_url_rejects_unsafe_secret_destinations(url: str) -> None:
    with pytest.raises(ValueError, match="Provider base URL is invalid or unsafe"):
        validate_provider_base_url(url, allow_insecure_loopback=False)


def test_provider_base_url_allows_https_and_explicit_loopback_development() -> None:
    assert (
        validate_provider_base_url(
            "https://provider.example/compatible-mode/v1",
            allow_insecure_loopback=False,
        )
        == "https://provider.example/compatible-mode/v1"
    )
    assert (
        validate_provider_base_url(
            "http://127.0.0.1:11434/v1", allow_insecure_loopback=True
        )
        == "http://127.0.0.1:11434/v1"
    )
    with pytest.raises(ValueError):
        validate_provider_base_url(
            "http://provider.example/v1", allow_insecure_loopback=True
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    ],
)
def test_v3_model_studio_base_url_requires_an_exact_allowlisted_endpoint(url: str) -> None:
    assert validate_model_studio_base_url(url) == url

    with pytest.raises(ValueError, match="outside the V3 allowlist"):
        validate_model_studio_base_url("https://provider.example/compatible-mode/v1")
    with pytest.raises(ValueError, match="outside the V3 allowlist"):
        validate_model_studio_base_url(url.replace("/compatible-mode/v1", "/api/v1"))


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "input_price", "output_price"),
    [
        ([-1], 100, 1.0, 1.0),
        ([100], 0, 1.0, 1.0),
        ([100], 100, -1.0, 1.0),
        ([100], 100, math.nan, 1.0),
    ],
)
def test_benchmark_cost_ceiling_rejects_invalid_bounds(
    input_tokens: list[int], output_tokens: int, input_price: float, output_price: float
) -> None:
    with pytest.raises(ValueError):
        calculate_cost_ceiling(
            input_tokens,
            max_output_tokens_per_case=output_tokens,
            input_price_per_million=input_price,
            output_price_per_million=output_price,
        )


def test_runner_refuses_over_budget_before_constructing_provider_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "0.00000001",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "exceeds approved maximum" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not (tmp_path / "must-not-exist.json").exists()


def test_runner_rejects_unknown_exact_case_before_constructing_provider_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--case-id",
            "not-a-real-case",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "1",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "Unknown --case-id" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not (tmp_path / "must-not-exist.json").exists()


def test_qwen38_runner_requires_the_exact_model_studio_endpoint_before_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "alibaba-model-studio",
            "--model",
            "qwen3.8-max",
            "--base-url",
            "https://provider.example/compatible-mode/v1",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--case-id",
            "zh-01",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "1",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "outside the V3 allowlist" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not (tmp_path / "must-not-exist.json").exists()


def test_runner_preflight_is_non_billable_and_does_not_require_a_key(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "alibaba-model-studio",
            "--model",
            "qwen3.8-max",
            "--base-url",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--case-id",
            "zh-01",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "1",
            "--currency",
            "USD",
            "--preflight-only",
        ],
        check=False,
        capture_output=True,
        env={key: value for key, value in os.environ.items() if key != "BENCHMARK_TEST_KEY"},
        text=True,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert "at most 1 provider calls" in process.stdout
    assert "preflight" in process.stdout.casefold()
    assert not (tmp_path / "must-not-exist.json").exists()


def test_runner_budgets_for_all_agent_tool_rounds_before_provider_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--category",
            "agent_tools",
            "--limit",
            "1",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "0.01",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "exceeds approved maximum" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr


def test_runner_refuses_existing_output_before_constructing_provider_client(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing.json"
    output.write_text('{"evidence": "preserve"}', encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(output),
            "--limit",
            "1",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "1",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "Refusing to overwrite" in process.stdout
    assert output.read_text(encoding="utf-8") == '{"evidence": "preserve"}'
    assert "not-a-real-key" not in process.stdout + process.stderr


def test_model_runner_rejects_unsafe_base_url_before_provider_client(
    tmp_path: Path,
) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--provider",
            "test-provider",
            "--model",
            "test-model",
            "--base-url",
            "http://secret-provider.example/v1",
            "--api-key-env",
            "BENCHMARK_TEST_KEY",
            "--output",
            str(tmp_path / "model.json"),
            "--limit",
            "1",
            "--input-price-per-million",
            "1",
            "--output-price-per-million",
            "1",
            "--max-cost",
            "1",
            "--currency",
            "USD",
            "--allow-billable",
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "BENCHMARK_TEST_KEY": "not-a-real-key"},
        text=True,
    )

    assert process.returncode == 2
    assert "invalid or unsafe" in process.stdout
    assert "secret-provider" not in process.stdout + process.stderr
    assert "not-a-real-key" not in process.stdout + process.stderr
