"""Every variable the owner is told to set must be read by real code.

``docs/recovery/OWNER_ACTIONS_ONLY.md`` is the one document the owner acts on: it
names the environment variables to place in the protected env files. Twice now a
name it recommended was read by nothing — an earlier round told the owner to set
``DEEPSEEK_API_KEY``, which no service reads, and the TypeSafe section recommended
``TYPESAFE_MODEL`` while the adapter only accepted a constructor argument. A
document that tells the owner to set a variable nobody reads wastes the one thing
the owner is being asked for.

So each documented name must resolve through one of the three mechanisms this
repository actually uses:

* an explicit Python env accessor — ``os.environ["NAME"]`` / ``os.environ.get("NAME")``
  / ``os.getenv("NAME")``;
* a pydantic settings field, whose environment name is the upper-cased field name
  (``v3_model_api_key`` reads ``V3_MODEL_API_KEY``);
* a TypeScript env accessor — ``process.env.NAME`` / ``environment.NAME``.

The check is deliberately about *reading*, not about mentioning: a name that only
appears in a docstring or a comment is exactly the defect it exists to catch.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OWNER_DOC = REPO_ROOT / "docs" / "recovery" / "OWNER_ACTIONS_ONLY.md"

# The code an owner-set environment actually feeds. Deliberately narrow: pytest's
# own fixtures under `work/` contain tens of thousands of files, and a variable
# read only by a test is not a variable the deployment honours.
SOURCE_ROOTS = ("services/rag-api/app", "services/agent-api/src", "scripts")
SOURCE_SUFFIXES = (".py", ".ts", ".mjs")
SKIPPED_PARTS = ("node_modules", ".venv", "__pycache__", "dist", "_mypy_probe")

VARIABLE_NAME = re.compile(r"\b((?:CMUI|V3|DEEPSEEK|AGENT|TYPESAFE|RAG)_[A-Z0-9_]+)\b")


def documented_names() -> set[str]:
    return set(VARIABLE_NAME.findall(OWNER_DOC.read_text(encoding="utf-8")))


def source_files(root: str) -> list[pathlib.Path]:
    return [
        path
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not any(part in str(path) for part in SKIPPED_PARTS)
    ]


def readers(name: str) -> list[str]:
    """Files that actually read ``name`` from the environment, by any mechanism."""
    py_accessor = re.compile(
        rf"(?:environ(?:\.get)?\s*[\(\[]\s*|getenv\s*\(\s*)['\"]{re.escape(name)}['\"]"
    )
    ts_accessor = re.compile(
        rf"(?:process\.env\.|environment\.|environment\[['\"]){re.escape(name)}['\"]?"
    )
    settings_field = re.compile(rf"^\s*{re.escape(name.lower())}\s*:", re.MULTILINE)

    found: list[str] = []
    for root in SOURCE_ROOTS:
        for path in source_files(root):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if py_accessor.search(text) or ts_accessor.search(text) or settings_field.search(text):
                found.append(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_the_owner_document_still_names_variables_worth_checking() -> None:
    """Guards the check itself: a format change must not make it vacuous."""
    names = documented_names()

    assert len(names) >= 10, (
        "the owner document no longer names the variables this test checks; "
        "either the table was reformatted or it lost its env-var instructions"
    )


def test_every_variable_the_owner_doc_names_is_read_by_code() -> None:
    unread = sorted(name for name in documented_names() if not readers(name))

    assert unread == [], (
        "OWNER_ACTIONS_ONLY.md tells the owner to set variables that no code reads: "
        + ", ".join(unread)
        + " - either wire them up or stop asking the owner for them"
    )


def test_the_typesafe_credential_is_read_by_the_service_itself() -> None:
    """Where the owner puts it is the service env, so the service must read it.

    The adapter used to take the key only as a constructor argument while the
    gateway built ``SdkTransport()`` with no arguments, so the guard always fired
    and the documented owner action could not enable the live path at all.
    """
    service_readers = [
        path for path in readers("TYPESAFE_API_KEY") if path.startswith("services/rag-api/app/")
    ]

    assert service_readers, (
        "TYPESAFE_API_KEY is not read anywhere under services/rag-api/app, so setting "
        "it in the service environment cannot enable the live Jev path"
    )
