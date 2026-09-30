"""Installing a qualification: the management entry point, and what it refuses.

A qualification row is the only thing that lets the hybrid gate publish, so the
command that writes one is the last place a mistake is cheap.  These tests pin the
refusals: an evaluation that did not pass, an artifact with no evidence identity,
and a target the copy guard does not accept.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "install_hybrid_qualification.py"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.install_hybrid_qualification import (  # noqa: E402
    _current_method_identity,
)

# The runtime facts a real run recorded.  The prompt, schema and combination
# versions are deliberately not listed here: they come from the code, which is
# the whole point of the identity check.
OBSERVED = {
    "api_surface_has_application_usd_cap": False,
    "endpoint_host": "api.deepseek.com",
    "model_alias": "deepseek-flash",
    "protocol": "responses",
    "provider": "DEEPSEEK_API",
}


def _artifact(**decision_overrides) -> dict:
    decision = {
        "status": "SCOPED_QUALITY_ACCEPTED",
        "policy_revision": "hybrid-strict-v1",
        "method_identity": _current_method_identity(OBSERVED),
        "reviewer_label": "SCOPED_QUALITY_ACCEPTED",
        "languages": ["en"],
        "domains": ["WORKSPACE_PRIVATE"],
        "cases": ["question.ambiguity.v1", "question.answer_agreement.v1"],
        "summary": {
            "positive_rows": 40,
            "negative_rows": 60,
            "independent_negative_families": 20,
        },
        "observed_model_facts": dict(OBSERVED),
    }
    decision.update(decision_overrides)
    return {
        "schema": "coursejesus.hybrid-qualification-run.v1",
        "created_at": "2026-09-30T00:00:00Z",
        "expires_at": "2026-10-30T00:00:00Z",
        "policy_revision": "hybrid-strict-v1",
        "dataset": {"digest": "b" * 64, "manifest": []},
        "row_outcomes": [],
        "decision": decision,
    }


def _run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        timeout=300,
    )


def _target_layout(tmp_path: Path) -> dict[str, Path]:
    production = tmp_path / "prod" / "rag.sqlite3"
    production.parent.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    copy = root / "rag.sqlite3"
    for path in (production, copy):
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT)"
        )
        for version in range(1, 66):
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, f"m{version}"),
            )
        connection.commit()
        connection.close()
    return {"production": production, "root": root, "copy": copy}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"status": "DRAFT"}, "only an accepted evaluation"),
        ({"reviewer_label": ""}, "no reviewer_label"),
        ({"cases": []}, "names no cases"),
    ],
)
def test_an_artifact_that_did_not_pass_is_refused(
    tmp_path: Path, override: dict, fragment: str
) -> None:
    layout = _target_layout(tmp_path)
    artifact = _write(tmp_path / "artifact.json", _artifact(**override))
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--qualification-id", "q-test",
        "--install",
    )
    assert result.returncode == 2
    assert fragment in result.stdout


def test_an_artifact_without_a_dataset_digest_is_refused(tmp_path: Path) -> None:
    layout = _target_layout(tmp_path)
    payload = _artifact()
    payload["dataset"] = {"manifest": []}
    artifact = _write(tmp_path / "artifact.json", payload)
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--qualification-id", "q-test",
        "--install",
    )
    assert result.returncode == 2
    assert "dataset digest" in result.stdout


def test_without_install_nothing_is_written(tmp_path: Path) -> None:
    """A dry run resolves the target exactly as the install would, and writes nothing.

    The production paths are declared here for the same reason the real install
    declares them: a writable purpose without them cannot be checked against
    anything, and that absence is itself a refusal.
    """
    layout = _target_layout(tmp_path)
    artifact = _write(tmp_path / "artifact.json", _artifact())
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--production-database", str(layout["production"]),
        "--qualification-id", "q-dry-run",
        "--expected-schema", "65",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["installed"] is False
    assert payload["method_identity"] == _current_method_identity(OBSERVED)
    assert payload["target"]["purpose"] == "QUALIFICATION_RUN"


def test_a_production_target_without_the_production_flag_is_refused(tmp_path: Path) -> None:
    layout = _target_layout(tmp_path)
    artifact = _write(tmp_path / "artifact.json", _artifact())
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["production"]),
        "--allowed-root", str(layout["root"]),
        "--production-database", str(layout["production"]),
        "--qualification-id", "q-test",
        "--install",
    )
    assert result.returncode == 6
    assert "DATABASE_TARGET_IS_PRODUCTION" in result.stdout


def test_an_artifact_from_a_superseded_method_is_refused(tmp_path: Path) -> None:
    """A qualification is bound to the procedure that was measured.

    The identity covers the prompt, schema *and* combination versions.  When one
    of those changes the artifact describes a procedure nobody can reproduce, so
    recording it would authorise the new procedure on the old procedure's
    evidence.
    """
    layout = _target_layout(tmp_path)
    artifact = _write(
        tmp_path / "artifact.json", _artifact(method_identity="a" * 64)
    )
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--qualification-id", "q-stale",
        "--install",
    )
    assert result.returncode == 2
    assert "different method identity" in result.stdout
    assert "re-measure" in result.stdout


def test_an_artifact_without_observed_model_facts_is_refused(tmp_path: Path) -> None:
    layout = _target_layout(tmp_path)
    artifact = _write(
        tmp_path / "artifact.json", _artifact(observed_model_facts=None)
    )
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--qualification-id", "q-test",
        "--install",
    )
    assert result.returncode == 2
    assert "observed model facts" in result.stdout


def test_a_production_write_must_name_a_production_database(tmp_path: Path) -> None:
    layout = _target_layout(tmp_path)
    artifact = _write(tmp_path / "artifact.json", _artifact())
    result = _run(
        "--artifact", str(artifact),
        "--database", str(layout["copy"]),
        "--allowed-root", str(layout["root"]),
        "--production-database", str(layout["production"]),
        "--qualification-id", "q-test",
        "--production",
        "--install",
    )
    assert result.returncode == 6
    assert "DATABASE_TARGET_NOT_PRODUCTION" in result.stdout
