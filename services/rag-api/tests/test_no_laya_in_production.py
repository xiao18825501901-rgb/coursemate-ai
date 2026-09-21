"""The production tree must carry no Laya dependency, reference or network path.

The Laya direction was cancelled by the owner and archived under
``archive/laya-superseded-20260922/``. That archive is intentional history; everything
outside it must be free of Laya, because a stray import, a stray credential name or a
stray host would either break the build or quietly reintroduce an abandoned provider.

This is a real scan with an offender list, not a comment: it reads the files the
backend, the agent and the frontend actually ship, and it fails naming every hit.
"""

from __future__ import annotations

import re
from pathlib import Path

RAG_APP = Path(__file__).resolve().parents[1] / "app"
REPOSITORY = Path(__file__).resolve().parents[3]

# Directories that ship (or are executed) as part of the product.
SCANNED_ROOTS = (
    Path(__file__).resolve().parents[1] / "app",          # services/rag-api/app
    REPOSITORY / "services" / "agent-api" / "src",
    REPOSITORY / "apps" / "web" / "src",
    REPOSITORY / "scripts",
)
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".toml", ".html"}

# Anything mentioning Laya in a way that would matter at runtime.
FORBIDDEN = re.compile(
    r"app\.laya|from\s+app\s+import\s+laya|import\s+laya\b|"
    r"\bLAYA_[A-Z_]+\b|convaiinnovations|laya-multilingual|laya-inference|"
    r"\blaya\b",
    re.IGNORECASE,
)

# The archived round is history and is explicitly allowed to mention Laya.
EXCLUDED_PARTS = {"archive", "node_modules", ".venv", "__pycache__", "dist", "build"}


def _candidate_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            if EXCLUDED_PARTS & set(path.parts):
                continue
            files.append(path)
    return sorted(files)


def test_no_laya_reference_in_the_production_tree() -> None:
    offenders: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in FORBIDDEN.finditer(text):
            line = text[: match.start()].count("\n") + 1
            snippet = text.splitlines()[line - 1].strip()[:120]
            offenders.append(f"{path.relative_to(REPOSITORY)}:{line}: {snippet}")

    assert offenders == [], (
        "the production tree still references the cancelled Laya provider; "
        "keep such code in archive/laya-superseded-20260922/ instead:\n" + "\n".join(offenders)
    )


def test_no_laya_dependency_is_declared() -> None:
    declared: list[str] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = RAG_APP.parent / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    continue
                if "laya" in stripped.casefold():
                    declared.append(f"{name}: {stripped}")
    assert declared == [], f"a Laya dependency is declared: {declared}"


def test_the_jev_semantic_layer_is_the_only_decision_provider() -> None:
    """The live semantic transport must be the Jev SDK, and it must stay lazy."""
    gateway = (RAG_APP / "jev" / "gateway.py").read_text(encoding="utf-8")
    assert "typesafe_sdk" in gateway, "the Jev SDK import disappeared from the gateway"
    # It may only be imported inside the transport, never at module import time.
    top_level = [
        line
        for line in gateway.splitlines()
        if line.startswith(("import ", "from ")) and "typesafe_sdk" in line
    ]
    assert top_level == [], f"the Jev SDK must be imported lazily, found {top_level}"
    assert (RAG_APP / "jev" / "callsites.py").is_file(), "the Jev call-site module is missing"
    assert not (RAG_APP / "laya").exists(), "the archived Laya package is back in the app tree"
