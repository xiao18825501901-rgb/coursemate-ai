"""Offline contract tests for the bounded P5 Question Engine live runner.

The CLI is exercised only in preflight/refusal modes.  No provider transport is
constructed and no network request can occur in this module.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[3]
RUNNER = ROOT / "scripts" / "run_question_engine_p5_live.py"


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p5_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_is_default_and_lists_the_finite_c1_c2_plan(tmp_path: Path) -> None:
    result = run_cli("--run-dir", str(tmp_path / "unused"))

    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT_ONLY" in result.stdout
    assert "DeepSeek calls: at most 8" in result.stdout
    assert "Jev calls: at most 4" in result.stdout
    assert "C1" in result.stdout and "C2" in result.stdout
    assert not (tmp_path / "unused").exists()


def test_billable_run_requires_both_protected_credentials(tmp_path: Path) -> None:
    result = run_cli(
        "--allow-billable",
        "--run-dir",
        str(tmp_path / "run"),
        "--cost-policy",
        "owner_authorized_unlimited_for_this_workflow",
        "--input-price-per-million",
        "1",
        "--output-price-per-million",
        "2",
        "--deepseek-key-env",
        "P5_TEST_MISSING_DEEPSEEK_KEY",
        "--jev-key-env",
        "P5_TEST_MISSING_JEV_KEY",
    )

    assert result.returncode == 2
    assert "Missing protected credential" in result.stdout
    assert not (tmp_path / "run").exists()


def test_capped_policy_refuses_without_a_positive_max_cost(tmp_path: Path) -> None:
    result = run_cli(
        "--allow-billable",
        "--run-dir",
        str(tmp_path / "run"),
        "--input-price-per-million",
        "1",
        "--output-price-per-million",
        "2",
    )

    assert result.returncode == 2
    assert "--max-cost is required" in result.stdout
    assert not (tmp_path / "run").exists()


def test_required_jev_modes_are_exactly_the_four_p5_gates() -> None:
    runner = load_runner()

    assert runner.REQUIRED_JEV_MODES == {
        "question.ambiguity.v1": "on",
        "question.answer_agreement.v1": "on",
        "question.mcq_distractor_quality.v1": "on",
        "question.rule_violation_quality.v1": "on",
    }
    assert runner.NON_REQUIRED_JEV_MODES_OFF == {
        "retrieval.support.v1": "off",
        "source.select_span.v1": "off",
    }
    assert runner.C1_C2_PLAN.deepseek_calls == 8
    assert runner.C1_C2_PLAN.jev_calls == 4


def test_cost_ceiling_is_computed_from_finite_call_and_token_caps() -> None:
    runner = load_runner()

    ceiling = runner.conservative_cost_ceiling(
        runner.C1_C2_PLAN,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    assert ceiling == 8 * ((15_000 * 1.0 + 4_000 * 2.0) / 1_000_000)


def test_call_budgets_refuse_before_an_extra_provider_attempt() -> None:
    runner = load_runner()
    budget = runner.CallBudget.create(deepseek_limit=2, jev_limit=1)

    budget.claim_deepseek("QUESTION_AUTHOR")
    budget.claim_deepseek("QUESTION_BLIND_SOLVER")
    budget.claim_jev("question.ambiguity.v1")

    with pytest.raises(RuntimeError, match="P5_DEEPSEEK_CALL_CAP_REACHED"):
        budget.claim_deepseek("PRACTICE_HINT")
    with pytest.raises(RuntimeError, match="P5_JEV_CALL_CAP_REACHED"):
        budget.claim_jev("question.answer_agreement.v1")
    assert budget.deepseek_roles == ["QUESTION_AUTHOR", "QUESTION_BLIND_SOLVER"]
    assert budget.jev_definitions == ["question.ambiguity.v1"]
    assert budget.audit_snapshot() == {
        "deepseek_limit": 2,
        "deepseek_attempted_roles": ["QUESTION_AUTHOR", "QUESTION_BLIND_SOLVER"],
        "jev_limit": 1,
        "jev_attempted_definitions": ["question.ambiguity.v1"],
    }


def test_mounted_ui_environment_uses_the_same_frozen_price_and_output_bounds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_runner()
    args = runner.parse_args(
        [
            "--run-dir",
            str(tmp_path / "run"),
            "--input-price-per-million",
            "0.3",
            "--output-price-per-million",
            "1.2",
            "--max-output-tokens",
            "4000",
        ]
    )
    for name in (
        "TYPESAFE_API_KEY",
        "CMUI_OPERATION_USD_BASELINE",
        "CMUI_OPERATION_INPUT_USD_PER_MILLION",
        "CMUI_OPERATION_OUTPUT_USD_PER_MILLION",
        "CMUI_ANSWER_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)

    runner._configure_process_environment(
        args,
        run_dir=(tmp_path / "run").resolve(),
        deepseek_key="test-deepseek",
        jev_key="test-jev",
        conservative_ceiling=0.0744,
    )

    assert os.environ["CMUI_OPERATION_USD_BASELINE"] == "0.07440000"
    assert os.environ["CMUI_OPERATION_INPUT_USD_PER_MILLION"] == "0.3"
    assert os.environ["CMUI_OPERATION_OUTPUT_USD_PER_MILLION"] == "1.2"
    assert os.environ["CMUI_ANSWER_TOKENS"] == "4000"

    from app.cm_update.budget import evaluate_operation_budget
    from app.cm_update.config import Settings as UiSettings
    from app.cm_update.provider import DeepSeekProvider

    ui_settings = UiSettings()
    ui_settings.validate()
    estimate = DeepSeekProvider(ui_settings).estimate_question_engine()
    decision = evaluate_operation_budget(
        "medium", ui_settings.operation_usd_baseline, estimate.usd
    )
    assert decision.application_usd_cap is not None
    assert estimate.output_tokens == 8_000


def test_prior_failed_attempt_is_hash_linked_without_private_material(tmp_path: Path) -> None:
    runner = load_runner()
    state = tmp_path / "run-state.json"
    state.write_text(
        json.dumps(
            {
                "status": "FAILED_SAFE",
                "application_sha": "abc123",
                "deepseek_calls": 0,
                "jev_calls": 2,
                "call_budget_audit": {
                    "deepseek_attempted_roles": [],
                    "jev_attempted_definitions": [
                        "retrieval.support.v1",
                        "source.select_span.v1",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    summary = runner._prior_attempt_summary(state)

    assert summary is not None
    assert summary["status"] == "FAILED_SAFE"
    assert summary["jev_calls"] == 2
    assert summary["state_sha256"] == __import__("hashlib").sha256(
        state.read_bytes()
    ).hexdigest()
