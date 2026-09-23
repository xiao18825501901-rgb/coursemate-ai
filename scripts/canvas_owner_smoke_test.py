"""Run the small-sample live Canvas read with a token the owner supplies locally.

The token is read through a **hidden prompt** (or from a protected file named by
`--token-file`), is held by the same in-process store the product uses, and is destroyed when the
read finishes. It is never written to a file, never printed, and never passed as a command-line
argument — a token on a command line is in the shell history and in the process list.

Typical use, from the repository root::

    services/rag-api/.venv/Scripts/python.exe scripts/canvas_owner_smoke_test.py --institution cityu

The receipt (identity, course, per-file sizes and hashes, and what happened to the credential) is
printed and, with `--receipt PATH`, written as JSON. Nothing is imported, parsed, indexed or stored:
this measures the read path, and it creates no course and no document.

Exit codes: 0 when a file was read and the credential was destroyed, 1 when the school or the
credential refused, 2 when the arguments or the deployment are wrong.
"""

from __future__ import annotations

import argparse
import getpass
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "rag-api"))

from app.canvas.adapter import CanvasReadAdapter  # noqa: E402
from app.canvas.owner_smoke import DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES, run_smoke  # noqa: E402
from app.canvas.registry import (  # noqa: E402
    InstitutionConnectionRegistry,
    UnknownInstitutionError,
)
from app.canvas.transient_credential import (  # noqa: E402
    SELECTION_IDLE_TTL_SECONDS,
    TransientCanvasCredentialStore,
)

MIN_TOKEN_CHARS = 8


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--institution", required=True, help="the school's registry key, e.g. cityu"
    )
    parser.add_argument(
        "--course", default="", help="a Canvas course id; default: first readable one"
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--token-file",
        default="",
        help="read the token from this file instead of prompting (the file is not deleted)",
    )
    parser.add_argument("--receipt", default="", help="write the JSON receipt to this path")
    parser.add_argument(
        "--sink",
        default="",
        help="directory for the temporary download (default: a temporary directory)",
    )
    return parser.parse_args(argv)


def read_token(path: str) -> str:
    """The token, from a protected file or a hidden prompt. Never from argv, never echoed.

    A file that is empty or holds whitespace returns an empty string rather than raising: the
    caller then refuses it through the same check as any other unusable value, with one exit code.
    """
    if path:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()
    entered = getpass.getpass("Canvas personal access token (input hidden): ").strip()
    return entered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = InstitutionConnectionRegistry()
    try:
        institution = registry.by_key(args.institution)
    except UnknownInstitutionError:
        known = ", ".join(item.key for item in registry.institutions)
        print(f"unknown institution {args.institution!r}; known: {known}", file=sys.stderr)
        return 2
    if institution.state != "AVAILABLE":
        print(
            f"the school {institution.key} is not usable on this machine ({institution.state}); "
            "the address is still what the read needs, and no client secret is required for it",
            file=sys.stderr,
        )

    token = read_token(args.token_file)
    if len(token) < MIN_TOKEN_CHARS:
        print(f"that does not look like a token ({len(token)} characters)", file=sys.stderr)
        return 2

    store = TransientCanvasCredentialStore()
    credential = store.open_task(
        subject="owner-live-test",
        connection_id="owner-live-test",
        institution_key=institution.key,
        institution_origin=institution.origin,
        token=token,
    )
    del token  # the only copy is the store's own buffer, which the run zeroes at the end

    adapter = CanvasReadAdapter(
        connection_id=credential.connection_id,
        origin=institution.origin,
        token_provider=store.provider(credential.credential_ref),
        registry=registry,
    )
    sink = pathlib.Path(args.sink) if args.sink else REPO_ROOT / "work" / "current-change" / "smoke"
    receipt = run_smoke(
        adapter=adapter,
        store=store,
        credential_ref=credential.credential_ref,
        sink_dir=sink,
        course_id=args.course,
        max_files=max(0, args.max_files),
        max_bytes=max(1, args.max_bytes),
    )
    payload = receipt.as_dict()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.receipt:
        target = pathlib.Path(args.receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nreceipt written to {target}")
    print(
        f"\ncredential: {payload['credential_state']} after {payload['read_calls']} Canvas reads; "
        f"{payload['zeroed_bytes']} bytes blanked; idle lifetime {int(SELECTION_IDLE_TTL_SECONDS)}s"
    )
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
