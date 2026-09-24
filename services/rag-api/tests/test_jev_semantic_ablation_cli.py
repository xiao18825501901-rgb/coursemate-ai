"""The semantic-ablation CLI must never label a fake run as live.

This file used to reproduce one defect and pin its refusal: with ``TYPESAFE_API_KEY`` and
``DEEPSEEK_API_KEY`` present and ``--allow-billable``, ``--transport live`` passed the preflight,
ran ``FakeJevTransport``, exited 0, and wrote an artefact whose top-level ``transport`` field said
``live`` while every number in it came from the fake transport.

The refusal that closed it has since been replaced by real wiring — the Jev half of the semantic
harness now calls the live transport — so the *property* is asserted instead of the refusal: an
artefact labelled ``live`` must correspond to real transport calls, its per-arm call log must carry
the answers that transport produced, and a run that refuses must leave nothing behind.

These tests drive ``main()`` directly rather than spawning a process, so they also cover the CLI
that nothing covered before.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from app.jev.models import JevAnswer, JevResult

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
COMPANION = REPO_ROOT / "benchmarks" / "jev-module-judgments.dataset.json"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_jev_semantic_ablation as cli  # noqa: E402  (import after the path insert)


def run_cli(monkeypatch: pytest.MonkeyPatch, out: pathlib.Path, *arguments: str) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_jev_semantic_ablation.py",
            "--arm",
            "M-TOOL",
            "--dataset",
            str(COMPANION),
            "--out",
            str(out),
            *arguments,
        ],
    )
    return cli.main()


def test_live_transport_makes_real_calls_and_never_labels_a_fake_run_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guarantee that used to be a refusal, asserted directly now that live wiring exists.

    The refusal existed because a live run fell through to the fake transport and then wrote an
    artefact whose `transport` said `live`. The live branch is now wired to the real transport, so
    what has to hold is the property the refusal protected: the artefact may say `live` only if the
    answers came from somewhere other than the fake predictor, and a refusal may leave nothing
    behind. The recording transport below stands in for `SdkTransport` (it is not a
    `FakeJevTransport`, so it counts as live) and answers with values the fake could not produce.
    """
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy-not-a-real-key")
    out = tmp_path / "live.json"
    calls: list[str] = []

    class RecordingTransport:
        def call(self, call, *, timeout_seconds: float):
            calls.append(timeout_seconds and "called")
            question = next(iter(call.questions.values()))
            primitive = str(question.primitive).lower()
            if primitive == "choice":
                answer = JevAnswer(choice=next(iter(question.criteria or {}), None))
            elif primitive == "score":
                answer = JevAnswer(score_value=2.0)
            else:
                answer = JevAnswer(noul=0.9)
            return JevResult(answers={"q": answer}, request_id="req", model_version="recording")

    monkeypatch.setattr(cli, "SdkTransport", RecordingTransport)

    code = run_cli(monkeypatch, out, "--transport", "live", "--allow-billable")

    if code != 0:
        assert not out.exists(), "a refused run must leave no artefact"
        assert "efus" in capsys.readouterr().out
        return
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["transport_used"] == "live"
    assert calls, "an artefact labelled live must correspond to real transport calls"
    calls_in_artifact = [
        call for arm in payload["arms"] for call in (arm.get("live_calls") or [])
    ]
    assert calls_in_artifact, "each arm must record the calls it made"
    # The fake predictor returns the first candidate, level 0 and `noul=False`, and the fake
    # transport reports no model version. Every recorded call naming the recording transport's
    # model is how the artefact is proved not to be fake output.
    assert calls_in_artifact
    assert all(call.get("model_version") == "recording" for call in calls_in_artifact)
    assert all(call.get("request_id") == "req" for call in calls_in_artifact)


def test_live_transport_without_authorization_still_preflights(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The preflight keeps its own refusal: no keys, no --allow-billable, no run."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    out = tmp_path / "unauthorized.json"

    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, out, "--transport", "live")

    assert exit_info.value.code == 2
    assert not out.exists()


def test_offline_run_records_the_transport_that_actually_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The artefact names both the requested transport and the one used."""
    out = tmp_path / "offline.json"

    code = run_cli(monkeypatch, out, "--transport", "fake")

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["transport"] == "fake"
    assert payload["transport_used"] == "deterministic_fake"


def run_components(
    monkeypatch: pytest.MonkeyPatch, out: pathlib.Path, *arguments: str
) -> int:
    """Drive the CLI over every component arm, letting the dataset flags be varied."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_jev_semantic_ablation.py",
            "--arm",
            "all-components",
            "--out",
            str(out),
            *arguments,
        ],
    )
    return cli.main()


def test_a_component_run_reads_both_datasets_and_says_which_metric_came_from_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """No single dataset labels all six modules, so the run reads both and records it.

    Run against either file alone this printed a page of ``INSUFFICIENT_SAMPLES``: the
    primary dataset has no extraction/entity/consistency/capability/tool samples, and the
    companion has no citation sample at all. Five arms measured nothing while the sixth
    printed real numbers, which reads like a complete table.
    """
    out = tmp_path / "components.json"

    code = run_components(monkeypatch, out, "--transport", "fake")

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    sources = {pathlib.Path(source["path"]).name: source for source in payload["dataset_sources"]}
    assert set(sources) == {"jev-judgments.dataset.json", "jev-module-judgments.dataset.json"}
    # Counts as of round 95, when both datasets grew so the definitions the promotion gate
    # depends on have a calibration population (`retrieval.support.v1` had none) and a test
    # population (`pedagogy.next_method.v1`, `extraction.field_grounded.v1` had none either).
    assert sources["jev-judgments.dataset.json"]["samples"] == 345
    assert sources["jev-module-judgments.dataset.json"]["samples"] == 54
    # Each dataset is pinned by its own frozen split, which is the provenance a later
    # reader needs to tie a metric to the split a temperature was fitted against.
    assert all(source["split_content_hash"] for source in sources.values())

    arms = {arm["arm"]: arm for arm in payload["arms"]}
    assert set(arms) == set(cli.COMPONENT_ARM_NAMES)
    for arm in arms.values():
        measured = {
            name: metric
            for name, metric in arm["component"]["metrics"].items()
            if metric["status"] == "MEASURED"
        }
        assert measured, f"{arm['arm']} measured nothing"
        assert set(arm["metric_sources"]) == set(arm["component"]["metrics"])
    # The citation metrics come from the primary dataset and the module metrics from the
    # companion — the whole point of reading both.
    assert (
        pathlib.Path(arms["M-CITATION"]["metric_sources"]["citation_support_accuracy"]).name
        == "jev-judgments.dataset.json"
    )
    assert (
        pathlib.Path(arms["M-EXTRACT"]["metric_sources"]["extraction_false_acceptance"]).name
        == "jev-module-judgments.dataset.json"
    )


def test_a_component_run_that_measures_nothing_is_refused_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A table of ``INSUFFICIENT_SAMPLES`` is not a result, so it is not written.

    ``--no-module-dataset`` is how an operator asks for the old behaviour, and it is exactly
    the case that must refuse: against the primary dataset alone, five of the six arms have
    no labelled sample at all.
    """
    out = tmp_path / "empty.json"

    code = run_components(
        monkeypatch,
        out,
        "--transport",
        "fake",
        "--no-module-dataset",
    )

    assert code == 4
    assert not out.exists(), "a refused run must leave no artefact"
    printed = capsys.readouterr().out
    assert "Refusing to write" in printed
    for arm in ("M-EXTRACT", "M-ENTITY", "M-CONSISTENCY", "M-CAPABILITY", "M-TOOL"):
        assert arm in printed


def test_component_arm_metrics_refuses_a_non_component_arm() -> None:
    """The accessor names the arms it knows instead of returning an empty mapping."""
    from app.evaluation.jev_semantic_ablation import component_arm_metrics

    with pytest.raises(ValueError, match="not a component arm"):
        component_arm_metrics("A")
    assert component_arm_metrics("M-CITATION") == (
        ("citation_support_accuracy", "source.supports_claim.v1"),
        ("unsupported_claim_rate", "source.supports_claim.v1"),
        ("span_selection_accuracy", "source.select_span.v1"),
    )
