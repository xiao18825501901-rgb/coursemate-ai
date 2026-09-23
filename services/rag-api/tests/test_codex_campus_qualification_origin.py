"""Campus qualification provenance: no registration auto-grant, an honest origin
per row, and a policy that can be strict without changing the default.

What this file pins, and why each pin exists:

- A new registration holds no qualification at all (`verified=0`, `method IS
  NULL`) and is refused on the real campus routes. It used to be granted
  `method='registered'` by the first authenticated request.
- A redeemed 7-digit code still grants and still records `method='code'`.
- `social.qualification_origin` separates a real verification
  (`code`/`admin`/`grandfathered`) from the old registration-auto source
  (`registered`), and `social.qualification_origin_counts` reports the three
  classes as aggregates.
- `campus_qualification_policy='verified_only'` refuses a `registered`-only user
  on both gates (the shell's `course_gate` and the injected authorizer the legacy
  V3 routes go through) while a `code` user is allowed.
- The default policy still allows a historical `registered` row: that is the
  deliberate, stated decision of this change. Nothing is downgraded, and no test
  here deletes a user, a course, a grade or a verification row.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_current_change_features import (  # noqa: F401
    UI,
    FakeAuthVerifier,
    FakeEmbeddingProvider,
    auth,
    make_course,
    make_settings,
)

from app.main import create_app

# The shared `client` fixture (a real host app on the labelled test provider) is
# taken from the module that owns it, declared as a plugin rather than imported,
# so the fixture keeps its name without shadowing an import.
pytest_plugins = ["test_current_change_features"]

CAMPUS_COURSE = "cs3481"


@pytest.fixture
def strict_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The same real host app with the strict policy, selected the way a
    deployment selects it: through the environment, before the extension mounts.

    A separate fixture rather than a live mutation of the default `client`,
    because `verified_only` is read when the `cmui` settings are built. The
    default policy's behaviour is pinned by the tests that use `client`.
    """
    monkeypatch.setenv("CMUI_PROVIDER_MODE", "test")
    monkeypatch.setenv("CMUI_AUTO_VERIFY_NEW_USERS", "false")
    monkeypatch.setenv("CMUI_CAMPUS_QUALIFICATION_POLICY", "verified_only")
    application = create_app(
        settings=make_settings(tmp_path),
        embedding_provider=FakeEmbeddingProvider(),
        auth_verifier=FakeAuthVerifier(),
    )
    with TestClient(application) as test_client:
        yield test_client


def ui_db(client: TestClient):
    return client.app.state.ui_extension_app.state.db


def verification_row(client: TestClient, owner: str):
    return ui_db(client).one("SELECT * FROM cmui_verification WHERE owner=?", (owner,))


def ensure_actor(client: TestClient, token: str) -> None:
    """Create a synthetic actor's local projection. Qualifies nothing.

    `cmui_verification` has a foreign key to `cmui_users`, so a test that
    simulates a historical row must first let the real authenticated request path
    create the account — which, since the auto-grant is gone, leaves it unverified.
    """
    assert client.get(f"{UI}/me", headers=auth(token)).status_code == 200


def test_a_new_registration_is_unverified_and_campus_content_is_refused(client: TestClient) -> None:
    """`verified=0`, `method IS NULL`, and every campus content route refuses."""
    make_course(client)
    # Asking for the status is itself an authenticated request, so it is the
    # first thing a brand-new registration does.
    status = client.get(f"{UI}/me/verification", headers=auth("token-c"))
    assert status.status_code == 200, status.text
    assert status.json() == {"verified": False, "method": None, "verified_at": None}
    assert verification_row(client, "user-c") is None, (
        "a registration must not write a qualification row at all"
    )

    # The same routes the campus deny matrix uses, still refused for an actor who
    # was never granted anything (nothing was deleted to deny them).
    refused = {
        "files": client.get(f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-c")),
        "pin": client.put(f"{UI}/courses/{CAMPUS_COURSE}/pin", headers=auth("token-c")),
        "knowledge": client.get(f"{UI}/courses/{CAMPUS_COURSE}/knowledge", headers=auth("token-c")),
        "comments": client.get(f"{UI}/courses/{CAMPUS_COURSE}/comments", headers=auth("token-c")),
        "documents": client.get(f"/api/courses/{CAMPUS_COURSE}/documents", headers=auth("token-c")),
    }
    assert {name: response.status_code for name, response in refused.items()} == {
        "files": 403, "pin": 403, "knowledge": 403, "comments": 403, "documents": 403,
    }, {name: response.text for name, response in refused.items()}
    # Course metadata stays visible: only content is gated.
    assert client.get(f"{UI}/courses/{CAMPUS_COURSE}", headers=auth("token-c")).status_code == 200


def test_redeeming_a_valid_code_still_grants_and_keeps_method_code(client: TestClient) -> None:
    make_course(client)
    codes = client.post(
        f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 1}
    ).json()["codes"]
    files = client.get(f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-c"))
    assert files.status_code == 403

    redeemed = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-c"),
        json={"code": codes[0], "request_id": "origin-code-grant"},
    )
    assert redeemed.status_code == 200, redeemed.text
    status = client.get(f"{UI}/me/verification", headers=auth("token-c")).json()
    assert status["verified"] is True and status["method"] == "code"
    assert verification_row(client, "user-c")["boundary_notes"].startswith("redeemed ")
    allowed = client.get(f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-c"))
    assert allowed.status_code == 200


def test_a_registration_auto_row_cannot_prove_real_verification(client: TestClient) -> None:
    """The data gap, pinned on a real database.

    A user who redeemed a code *after* being auto-granted keeps
    `method='registered'`, because `redeem_code` deliberately refuses to
    overwrite an already verified provenance. `cmui_verification` alone therefore
    cannot prove they were really verified; only
    `cmui_verification_codes.status='redeemed'` for the same owner can.
    """
    make_course(client)
    codes = client.post(
        f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 1}
    ).json()["codes"]
    from app.cm_update import social

    # Reproduce the historical shape: a registration-auto row, then a real
    # redemption by the same owner.
    db = ui_db(client)
    ensure_actor(client, "token-d")
    social.set_verified(db, "user-d", "registered", "historical registration auto grant")
    redeemed = client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-d"),
        json={"code": codes[0], "request_id": "gap-redeem-after-auto"},
    )
    assert redeemed.status_code == 200, redeemed.text
    after = client.get(f"{UI}/me/verification", headers=auth("token-d")).json()
    assert after["method"] == "registered"

    # The corroborating evidence the qualification table cannot carry:
    redeemed_code = db.one(
        "SELECT code_id,status,owner FROM cmui_verification_codes WHERE owner=?", ("user-d",)
    )
    assert redeemed_code is not None and redeemed_code["status"] == "redeemed"
    # ... and it is never printed or listed by the aggregate helpers.
    origin = social.qualification_origin(social.verification_status(db, "user-d"))
    assert origin == "registration_auto"


def test_qualification_origin_separates_real_from_registration_auto(tmp_path: Path) -> None:
    from app.cm_update import social
    from app.cm_update.db import Database

    db = Database(tmp_path / "origins.sqlite3")
    db.initialize()
    for owner in ("code", "admin", "grandfathered", "registered"):
        db.execute(
            "INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
            (owner, owner, "handle-" + owner, "2026-01-01T00:00:00Z"),
        )
        social.set_verified(db, owner, owner, "synthetic origin fixture")

    assert social.qualification_origin(social.verification_status(db, "code")) == "real"
    assert social.qualification_origin(social.verification_status(db, "admin")) == "real"
    assert social.qualification_origin(social.verification_status(db, "grandfathered")) == "real"
    registered = social.qualification_origin(social.verification_status(db, "registered"))
    assert registered == "registration_auto"

    # Not-yet-qualified shapes are never counted as real.
    assert social.qualification_origin(social.verification_status(db, "never")) == "none"
    assert social.qualification_origin(None) == "none"
    assert social.qualification_origin({"verified": 0, "method": "code"}) == "none"
    assert social.qualification_origin({"verified": 1, "method": None}) == "none", (
        "a verified row whose method proves nothing must not be reported as real"
    )


def test_qualification_origin_counts_reports_the_three_classes(tmp_path: Path) -> None:
    from app.cm_update import social
    from app.cm_update.db import Database

    db = Database(tmp_path / "counts.sqlite3")
    db.initialize()
    for owner in ("real-a", "real-b", "auto-a", "auto-b", "auto-c", "quiet"):
        db.execute(
            "INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
            (owner, owner, "handle-" + owner, "2026-01-01T00:00:00Z"),
        )
    social.set_verified(db, "real-a", "code", "redeemed")
    social.set_verified(db, "real-b", "admin", "operator")
    for owner in ("auto-a", "auto-b", "auto-c"):
        social.set_verified(db, owner, "registered", "historical registration auto grant")
    before = db.all("SELECT owner,verified,method FROM cmui_verification ORDER BY owner")

    counts = social.qualification_origin_counts(db)

    assert counts == {"real": 2, "registration_auto": 3, "none": 1}
    assert set(counts) == {"real", "registration_auto", "none"}
    assert json.dumps(counts).find("auto-a") == -1, "the aggregate must not leak an owner id"
    # Pure read: the qualification rows it classified are byte-for-byte unchanged.
    assert db.all("SELECT owner,verified,method FROM cmui_verification ORDER BY owner") == before


def test_origin_report_cli_prints_only_the_three_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.cm_update import qualification_origin_report as report
    from app.cm_update import social
    from app.cm_update.db import Database

    path = tmp_path / "cli.sqlite3"
    db = Database(path)
    db.initialize()
    for owner in ("real-a", "auto-a", "quiet"):
        db.execute(
            "INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
            (owner, owner, "handle-" + owner, "2026-01-01T00:00:00Z"),
        )
    social.set_verified(db, "real-a", "code", "redeemed")
    social.set_verified(db, "auto-a", "registered", "historical registration auto grant")

    monkeypatch.setattr(sys, "argv", ["qualification_origin_report", "--database", str(path)])
    assert report.main() == 0
    printed = capsys.readouterr().out

    assert json.loads(printed) == {"real": 1, "registration_auto": 1, "none": 1, "total": 3}
    for leaked in ("real-a", "auto-a", "quiet", "handle-"):
        assert leaked not in printed, f"the diagnostic printed an identifier: {leaked}"

    # A missing or non-UI database is refused, and refused without creating one.
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        report.origin_report(missing)
    assert not missing.exists()
    not_a_database = tmp_path / "not-a-database.sqlite3"
    not_a_database.write_bytes(b"not a database")
    with pytest.raises(ValueError):
        report.origin_report(not_a_database)
    assert not_a_database.read_bytes() == b"not a database"


def test_verified_only_refuses_registration_auto_and_allows_a_code(
    strict_client: TestClient,
) -> None:
    """Both gates honour the strict policy, with the existing error code."""
    from app.cm_update import social

    make_course(strict_client)
    db = ui_db(strict_client)
    # A historical registration-auto row (the shape the removed auto-grant wrote)
    # and a real code redemption, on two different synthetic actors.
    ensure_actor(strict_client, "token-d")
    social.set_verified(db, "user-d", "registered", "historical registration auto grant")
    codes = strict_client.post(
        f"{UI}/admin/verification-codes", headers=auth("admin-token"), json={"count": 1}
    ).json()["codes"]
    redeemed = strict_client.post(
        f"{UI}/me/verification/redeem", headers=auth("token-c"),
        json={"code": codes[0], "request_id": "strict-code-grant"},
    )
    assert redeemed.status_code == 200, redeemed.text
    strict_status = strict_client.get(f"{UI}/me/verification", headers=auth("token-c")).json()
    assert strict_status["method"] == "code"

    # The shell gate (cm_update.app.course_gate) refuses the registration-only user.
    refused = strict_client.get(f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-d"))
    assert refused.status_code == 403, refused.text
    # The legacy V3 authorizer (ui_extension.mount.authorize_content) refuses too,
    # with the existing stable error code and the existing Chinese message style.
    legacy = strict_client.get(f"/api/courses/{CAMPUS_COURSE}/documents", headers=auth("token-d"))
    assert legacy.status_code == 403, legacy.text
    assert legacy.json()["error"]["code"] == "STUDENT_VERIFICATION_REQUIRED"
    assert legacy.json()["error"]["message"].startswith("此课程为校园课程")

    # A provable origin is allowed on both gates.
    assert strict_client.get(
        f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-c")
    ).status_code == 200
    assert strict_client.get(
        f"/api/courses/{CAMPUS_COURSE}/documents", headers=auth("token-c")
    ).status_code == 200
    # The refusal is a decision about origin, not a deletion of anything:
    assert social.verification_status(db, "user-d")["verified"] is True
    assert verification_row(strict_client, "user-d")["method"] == "registered"


def test_the_default_policy_still_allows_a_historical_auto_row(client: TestClient) -> None:
    """The deliberate decision of this change: stop granting, do not revoke.

    Switching to `verified_only` is the owner's decision, and it has a cost:
    every `registered`-only account would newly be refused. Until the owner makes
    it, those accounts keep campus access and their rows keep their value.
    """
    from app.cm_update import social

    make_course(client)
    db = ui_db(client)
    ensure_actor(client, "token-d")
    social.set_verified(db, "user-d", "registered", "historical registration auto grant")
    before = db.all("SELECT owner,verified,method FROM cmui_verification ORDER BY owner")

    status = client.get(f"{UI}/me/verification", headers=auth("token-d")).json()
    assert status["verified"] is True and status["method"] == "registered"
    shell = client.get(f"{UI}/courses/{CAMPUS_COURSE}/files", headers=auth("token-d"))
    assert shell.status_code == 200
    legacy = client.get(f"/api/courses/{CAMPUS_COURSE}/documents", headers=auth("token-d"))
    assert legacy.status_code == 200
    origin = social.qualification_origin(social.verification_status(db, "user-d"))
    assert origin == "registration_auto"

    # The gate read the row; it did not rewrite or downgrade any row.
    assert db.all("SELECT owner,verified,method FROM cmui_verification ORDER BY owner") == before


def test_counts_on_the_route_seeded_database(client: TestClient) -> None:
    """On the database the real routes built: two explicitly granted actors, and
    the never-granted registration counted under `none` — not under
    `registration_auto`, because nothing auto-granted it."""
    from app.cm_update import social

    make_course(client)
    assert client.get(f"{UI}/me/verification", headers=auth("token-c")).status_code == 200

    assert social.qualification_origin_counts(ui_db(client)) == {
        "real": 2, "registration_auto": 0, "none": 1,
    }


def test_origin_report_on_a_database_that_predates_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shape the archived production snapshot actually has.

    That database is at UI schema 5: `cmui_users` exists, `cmui_verification`
    does not. The diagnostic must report honest zeroes plus every account as
    unqualified — and say why on stderr — rather than fail with a raw
    "no such table" or leave the reader to guess.
    """
    import sqlite3

    from app.cm_update import qualification_origin_report as report

    path = tmp_path / "pre-qualification.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE cmui_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE cmui_users (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " handle TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);"
            "INSERT INTO cmui_meta VALUES('schema_version','5');"
        )
        for index in range(3):
            connection.execute(
                "INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)",
                (f"legacy-{index}", f"Legacy {index}", f"legacy-handle-{index}", "2026-01-01"),
            )
    before = path.read_bytes()

    assert report.qualification_table_present(path) is False
    assert report.origin_report(path) == {
        "real": 0, "registration_auto": 0, "none": 3, "total": 3,
    }
    monkeypatch.setattr(sys, "argv", ["qualification_origin_report", "--database", str(path)])
    assert report.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"real": 0, "registration_auto": 0, "none": 3, "total": 3}
    assert "no cmui_verification table" in captured.err
    assert "legacy-" not in captured.out + captured.err
    # Read-only in the strictest sense: the file is byte-identical afterwards.
    assert path.read_bytes() == before
