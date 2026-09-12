import base64
import os
import subprocess
import sys
from pathlib import Path

from app.config import Settings
from app.evaluation.v3_model_canary import (
    call_input_token_ceilings,
    detect_image_media_type,
    load_v3_teaching_cases,
    run_image_problem_case,
    run_teaching_case,
)
from app.learning.provider import LearningProvider

ROOT = Path(__file__).parents[3]
DATASET = ROOT / "benchmarks" / "v3-teaching-canary-cases.json"
RUNNER = ROOT / "scripts" / "run_v3_model_canary.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def test_v3_canary_dataset_is_the_full_four_major_case_and_language_matrix() -> None:
    cases = load_v3_teaching_cases(DATASET)

    assert len(cases) == 8
    assert {(case.major, case.case_type) for case in cases} == {
        (major, case_type)
        for major in ("CS", "SMART_MANUFACTURING", "MATERIALS", "ENERGY")
        for case_type in ("CASE_A", "CASE_B")
    }
    assert {case.language for case in cases} == {"zh-CN", "en", "bilingual"}
    assert all(case.evidence_id in case.item.evidence_ids for case in cases)


def test_v3_canary_runs_real_v3_contract_chain_with_deterministic_provider() -> None:
    provider = LearningProvider(
        Settings(_env_file=None, app_env="test", rag_provider_mode="deterministic")
    )

    for case in load_v3_teaching_cases(DATASET):
        result = run_teaching_case(case, provider)
        assert result["automated_pass"] is True
        assert result["plan"]["case_type"] == case.case_type
        assert result["plan"]["schema_version"] == "v3.2"
        assert result["unit"]["completion_status"] == "COMPLETED"
        assert [run["role"] for run in result["runs"]] == ["planner", "teacher"]
        assert all(run["model"] == "FAKE_TEST_ONLY" for run in result["runs"])


def test_v3_canary_cost_preflight_reserves_every_call_and_image_payload() -> None:
    cases = load_v3_teaching_cases(DATASET)
    ceilings = call_input_token_ceilings(
        cases,
        max_output_tokens=4_000,
        image_content=PNG_1X1,
        image_media_type="image/png",
    )

    assert len(ceilings) == 17
    assert all(value > 0 for value in ceilings)
    assert ceilings[-1] > len(PNG_1X1)
    assert detect_image_media_type(PNG_1X1) == "image/png"
    assert detect_image_media_type(b"not an image") is None


def test_v3_image_canary_runs_the_problem_schema_without_claiming_verification() -> None:
    provider = LearningProvider(
        Settings(_env_file=None, app_env="test", rag_provider_mode="deterministic")
    )

    result = run_image_problem_case(
        provider,
        image_content=PNG_1X1,
        image_media_type="image/png",
    )

    assert result["automated_pass"] is True
    assert result["image"]["byte_size"] == len(PNG_1X1)
    assert result["output"]["verification"] == "NOT_INDEPENDENTLY_VERIFIED"
    assert result["manual_review"]["status"] == "REQUIRED"


def runner_command(tmp_path: Path, *extra: str) -> tuple[list[str], Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    image = tmp_path / "synthetic-addition.png"
    image.write_bytes(PNG_1X1)
    output = tmp_path / "result.json"
    command = [
        sys.executable,
        str(RUNNER),
        "--base-url",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "--api-key-env",
        "V3_CANARY_TEST_KEY",
        "--image",
        str(image),
        "--output",
        str(output),
        "--input-price-per-million",
        "1",
        "--output-price-per-million",
        "1",
        "--max-cost",
        "10",
        "--currency",
        "USD",
        "--max-provider-calls",
        "17",
        "--confirm-synthetic-image",
        *extra,
    ]
    return command, output


def run_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        env={**os.environ, "V3_CANARY_TEST_KEY": "not-a-real-key"},
        text=True,
    )


def test_v3_canary_runner_refuses_billable_calls_before_client_creation(
    tmp_path: Path,
) -> None:
    command, output = runner_command(tmp_path)

    process = run_runner(command)

    assert process.returncode == 2
    assert "allow-billable" in process.stdout
    assert "not-a-real-key" not in process.stdout + process.stderr
    assert not output.exists()


def test_v3_canary_runner_refuses_call_count_and_cost_overruns(tmp_path: Path) -> None:
    call_command, output = runner_command(
        tmp_path,
        "--allow-billable",
    )
    call_command[call_command.index("17")] = "16"
    calls = run_runner(call_command)
    assert calls.returncode == 2
    assert "17 provider calls" in calls.stdout
    assert not output.exists()

    cost_command, output = runner_command(
        tmp_path / "cost",
        "--allow-billable",
    )
    cost_command[cost_command.index("10")] = "0.00000001"
    cost = run_runner(cost_command)
    assert cost.returncode == 2
    assert "exceeds approved maximum" in cost.stdout
    assert "not-a-real-key" not in cost.stdout + cost.stderr
    assert not output.exists()


def test_v3_canary_preflight_is_non_billable_and_does_not_need_a_key(
    tmp_path: Path,
) -> None:
    command, output = runner_command(tmp_path, "--preflight-only")

    process = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env={key: value for key, value in os.environ.items() if key != "V3_CANARY_TEST_KEY"},
        text=True,
    )

    assert process.returncode == 0, process.stdout + process.stderr
    assert "17 provider calls" in process.stdout
    assert "preflight" in process.stdout.casefold()
    assert not output.exists()
