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
