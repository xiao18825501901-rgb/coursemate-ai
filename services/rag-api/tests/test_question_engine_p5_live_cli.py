"""Offline contract tests for the bounded P5 Question Engine live runner.

The CLI is exercised only in preflight/refusal modes.  No provider transport is
constructed and no network request can occur in this module.
"""

from __future__ import annotations

import importlib.util
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
    assert "Jev calls: at most 6" in result.stdout
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
    assert runner.C1_C2_PLAN.deepseek_calls == 8
    assert runner.C1_C2_PLAN.jev_calls == 6


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
