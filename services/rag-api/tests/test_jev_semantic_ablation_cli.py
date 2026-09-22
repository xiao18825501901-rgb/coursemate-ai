"""The semantic-ablation CLI must never label a fake run as live.

Reproduced before the fix: with ``TYPESAFE_API_KEY`` and ``DEEPSEEK_API_KEY``
present and ``--allow-billable``, ``--transport live`` passed the preflight, ran
``FakeJevTransport``, exited 0, and wrote an artefact whose top-level
``transport`` field said ``live`` while every number in it came from the fake
transport. The old comment justified the branch as unreachable "after
_live_preflight", which held only while the credentials were absent - exactly the
condition the live gate removes.

These tests drive ``main()`` directly rather than spawning a process, so they
also cover the CLI that nothing covered before.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

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


def test_live_transport_refuses_instead_of_running_the_fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both credentials present is exactly when the old code faked a live run."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy-not-a-real-key")
    out = tmp_path / "live.json"

    code = run_cli(monkeypatch, out, "--transport", "live", "--allow-billable")

    assert code == 3
    assert not out.exists(), "a refused live run must not leave an artefact behind"
    assert "no live predictor wiring" in capsys.readouterr().out


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
