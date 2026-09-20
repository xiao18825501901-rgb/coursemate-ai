#!/usr/bin/env python3
"""Create or deactivate one tightly scoped CourseMate release-test identity.

The program deliberately reads a short JSON payload only from standard input,
uses the protected Clerk key already installed on the production host, and never
prints an email address, password, or credential.  Deactivation bans the Clerk
user and projects that disabled status to the UI directory without deleting
the CourseMate audit rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ReleaseIdentityError(RuntimeError):
    """A deliberately non-sensitive release-test identity failure."""


def read_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        raise ReleaseIdentityError("Input must be one JSON object.") from error
    if not isinstance(payload, dict):
        raise ReleaseIdentityError("Input must be one JSON object.")
    return payload


def clerk_request(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    secret = os.environ.get("CLERK_SECRET_KEY", "").strip()
    if not secret:
        raise ReleaseIdentityError("The protected Clerk credential is unavailable.")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"https://api.clerk.com/v1/{path.lstrip('/')}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310: fixed Clerk HTTPS origin
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ReleaseIdentityError(f"Clerk {method} returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ReleaseIdentityError(f"Clerk {method} request failed.") from error
    if not isinstance(data, dict):
        raise ReleaseIdentityError("Clerk returned an invalid identity record.")
    return data


def create(payload: dict[str, Any]) -> None:
    email = payload.get("email")
    password = payload.get("password")
    label = payload.get("label")
    if (
        not isinstance(email, str)
        or not email.endswith("@example.com")
        or not isinstance(password, str)
        or len(password) < 16
        or not isinstance(label, str)
        or not label.startswith("four-changes-")
    ):
        raise ReleaseIdentityError("Release identity payload does not meet the synthetic-account contract.")
    user = clerk_request(
        "POST",
        "users",
        {
            "email_address": [email],
            "password": password,
            "first_name": "CourseMate",
            "last_name": "Release Test",
            "external_id": label,
        },
    )
    subject = user.get("id")
    if not isinstance(subject, str) or not subject.startswith("user_"):
        raise ReleaseIdentityError("Clerk did not return a valid synthetic subject.")
    print(f"RELEASE_TEST_IDENTITY_CREATED subject={subject}")


def deactivate(payload: dict[str, Any], rag_source: Path) -> None:
    subject = payload.get("subject")
    if not isinstance(subject, str) or not subject.startswith("user_"):
        raise ReleaseIdentityError("A Clerk user subject is required for deactivation.")
    user = clerk_request("PATCH", f"users/{subject}", {"banned": True})
    if user.get("id") != subject or user.get("banned") is not True:
        raise ReleaseIdentityError("Clerk did not confirm the test identity was banned.")
    data_dir = os.environ.get("CMUI_DATA_DIR", "").strip()
    if not data_dir:
        raise ReleaseIdentityError("The deployed UI data directory is unavailable.")
    sys.path.insert(0, str(rag_source / "services" / "rag-api"))
    from app.cm_update.db import Database  # noqa: PLC0415
    from app.cm_update.directory import sync_directory  # noqa: PLC0415

    database = Database(Path(data_dir) / "ui.sqlite3")
    sync_directory(database, [user], complete=False)
    print(f"RELEASE_TEST_IDENTITY_DEACTIVATED subject={subject} ui_directory=inactive")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "deactivate"))
    parser.add_argument("--rag-source", type=Path, required=True)
    args = parser.parse_args()
    if not args.rag_source.is_dir():
        parser.error("--rag-source must be an existing immutable release directory")
    try:
        payload = read_payload()
        if args.action == "create":
            create(payload)
        else:
            deactivate(payload, args.rag_source)
    except ReleaseIdentityError as error:
        print(f"RELEASE_TEST_IDENTITY_FAILED {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
