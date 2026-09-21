"""The ablation baseline must be the shipped pipeline, not a placeholder.

Verifying the harness surfaced two ways it could have produced a misleading
comparison once a live credential arrives:

* explicit commands (继续 / 暂停 / 做一题 / 交卷 …) were sent to the semantic layer
  instead of the deterministic router, so arm A looked worse than the product on
  exactly the commands the product answers without any model call;
* for the families where the non-Jev side is normally the existing reviewer, grader
  or citation check, an uninjected run records an *abstention* — which is not what
  the product ships.

These tests pin the fix: explicit commands are routed for real and spend no Jev call,
placeholder baselines are named in the run summary, and `compare_arms` refuses to call
a comparison interpretable while a placeholder baseline is in play.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.jev_ablation import (
    DATASET_STATUS_LABELLED,
    TRANSPORT_LIVE,
    compare_arms,
    load_ablation_cases,
    run_ablation,
)
from app.jev.gateway import FakeTransport
from app.jev.models import JevAnswer, JevResult

CASES = Path(__file__).parents[3] / "benchmarks" / "jev-ablation-cases.example.json"


class _RecordingTransport(FakeTransport):
    """Records every call so a test can prove a decision never reached Jev."""

    def __init__(self) -> None:
        def responder(call):  # noqa: ANN001
            keys = {key: JevAnswer(score="0", noul=0.0, choice=None) for key in call.questions}
            return JevResult(answers=keys)

        super().__init__(responder)
        self.calls: list[str] = []

    def __call__(self, call):  # noqa: ANN001
        self.calls.append(str(call.key))
        return super().__call__(call)


def _cases():
    return load_ablation_cases(CASES)


def test_explicit_commands_are_routed_without_a_jev_call() -> None:
    transport = _RecordingTransport()
    run = run_ablation(_cases(), "A", transport=transport)
    # Three of the four example turns are explicit commands: 继续, 暂停 and
    # "please continue the lesson". The compound sentence is deliberately not routed.
    assert run["explicit_command_turns_no_jev_call"] == 3
    # Arm A has every definition off, so nothing may reach Jev at all.
    assert run["jev_calls"] == 0


def test_explicit_command_family_recovers_the_mainline_in_the_baseline_arm() -> None:
    run = run_ablation(_cases(), "A", transport=_RecordingTransport())
    # 3 of the 4 example trajectories are answerable deterministically: the two explicit
    # commands plus "please continue the lesson". Only the compound sentence
    # "answer this detour then resume" is left to the semantic path.
    assert run["metrics"]["mainline_recovery_rate"] == pytest.approx(0.75)


def test_placeholder_baselines_are_named_in_the_run_summary() -> None:
    run = run_ablation(_cases(), "A", transport=_RecordingTransport())
    placeholders = run["placeholder_baselines"]
    assert "coverage:abstention" in placeholders
    assert "criterion:abstention" in placeholders
    assert "citation:abstention" in placeholders
    assert any(entry.startswith("trajectory:OTHER-default(") for entry in placeholders)


def test_injected_baselines_remove_the_placeholder_entries() -> None:
    run = run_ablation(
        _cases(),
        "A",
        transport=_RecordingTransport(),
        coverage_baseline=lambda case: case.label_supported,
        criterion_baseline=lambda case, item: {"accurate": 0, "partially": 1, "not": 2}[item.label],
        citation_baseline=lambda case: case.label_supported,
    )
    # The three injected families are no longer placeholders; the one trajectory turn
    # that is not an explicit command still is, and stays named as such.
    assert run["placeholder_baselines"] == ["trajectory:OTHER-default(1 turns)"]
    # With the real baselines injected the metrics reflect them, not abstention.
    assert run["metrics"]["criterion_error"] == 0.0
    assert run["metrics"]["coverage_confusion"]["fn"] == 0


def _live_run(**overrides) -> dict:
    run = run_ablation(_cases(), "A", transport=_RecordingTransport(), **overrides)
    run["transport"] = TRANSPORT_LIVE
    run["dataset_status"] = DATASET_STATUS_LABELLED
    run["placeholder_baselines"] = list(run["placeholder_baselines"])
    return run


def test_compare_arms_refuses_interpretable_with_a_placeholder_baseline() -> None:
    runs = {"A": _live_run(), "B": _live_run()}
    result = compare_arms(runs)
    assert result["verdict"] == "NOT_INTERPRETABLE"
    assert "placeholder baseline" in result["reason"]
    with pytest.raises(ValueError, match="placeholder baseline"):
        compare_arms(runs, request_quality=True)


def test_compare_arms_allows_interpretable_once_real_baselines_are_injected() -> None:
    baselines = {
        "coverage_baseline": lambda case: case.label_supported,
        "criterion_baseline": lambda case, item: 0,
        "citation_baseline": lambda case: case.label_supported,
    }
    runs = {"A": _live_run(**baselines), "B": _live_run(**baselines)}
    for run in runs.values():
        # No trajectory placeholder either: state that a real baseline router was used.
        run["placeholder_baselines"] = [
            entry
            for entry in run["placeholder_baselines"]
            if not entry.startswith("trajectory:")
        ]
    result = compare_arms(runs)
    assert result["verdict"] == "INTERPRETABLE"
    assert set(result["metrics_by_arm"]) == {"A", "B"}


def test_mainline_recovery_is_identical_across_arms_for_explicit_commands() -> None:
    """Anchors are fixed by construction: no arm may lose them.

    Before this was fixed, the harness asked Jev whether to keep the *fixed anchor*
    itself, so arms C/D scored 0.000 on the mainline metric purely because the
    transport answered "drop" — a penalty the product can never suffer, since it never
    offers anchors to the semantic layer.
    """
    runs = {
        arm: run_ablation(_cases(), arm, transport=_RecordingTransport())
        for arm in ("A", "B", "C", "D")
    }
    for arm, run in runs.items():
        assert run["metrics"]["mainline_recovery_rate"] == pytest.approx(0.75), arm
        assert all(case["anchor_preserved"] for case in run["per_case"]["trajectory"]), arm


def test_only_filterable_segments_are_offered_for_dropping() -> None:
    run = run_ablation(_cases(), "D", transport=_RecordingTransport())
    # The example trajectory case declares two filterable segments; the anchor is not
    # one of them. The non-informative transport says "drop", which is recorded as
    # advice — and changes nothing about the anchor.
    assert run["filterable_segments"]["considered"] == 2
    assert run["filterable_segments"]["kept"] == 0
    assert all(case["anchor_preserved"] for case in run["per_case"]["trajectory"])


def test_offline_run_can_never_be_interpretable(tmp_path: Path) -> None:
    run = run_ablation(_cases(), "A", transport=_RecordingTransport())
    assert run["interpretation"] != "INTERPRETABLE"
    assert compare_arms({"A": run})["verdict"] == "NOT_INTERPRETABLE"


def test_example_dataset_is_not_a_result_source() -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    assert payload["dataset_status"] == "EXAMPLE_NOT_LABELLED_FOR_RESULTS"
    assert _cases().dataset_status == "EXAMPLE_NOT_LABELLED_FOR_RESULTS"
