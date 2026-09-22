"""Job persistence: idempotent creation, lease-based claiming, per-file upserts."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta

from app.canvas.job import JobStateError, new_job
from app.canvas.store import CanvasJobRepository
from app.config import Settings
from app.db import Database

CITYU = "https://canvas.cityu.edu.hk"

# `Database.connect()` is a context manager; the repository needs the connection to stay
# open for the duration of a test, so the stacks are held here for the process lifetime.
_STACKS: list[ExitStack] = []


def repository(tmp_path) -> tuple[CanvasJobRepository, object]:
    database = Database(
        Settings(
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            app_env="test",
            v3_enabled=True,
            rag_provider_mode="deterministic",
            ui_web_dir=tmp_path / "no-web-build",
        )
    )
    database.initialize()
    stack = ExitStack()
    _STACKS.append(stack)
    connection = stack.enter_context(database.connect())
    connection.execute(
        "INSERT INTO canvas_connections(id, owner_user_id, institution_key, institution_origin, "
        "canvas_user_id) VALUES('conn-1','user-1','cityu',?, '4242')",
        (CITYU,),
    )
    return CanvasJobRepository(connection), connection


def make_job(job_id: str = "job-1", *, courses: list[str] | None = None):
    return new_job(
        job_id=job_id,
        connection_id="conn-1",
        subject="user-1",
        institution_origin=CITYU,
        course_ids=courses or ["560", "240"],
    )


def test_creating_a_job_then_asking_again_returns_the_same_row(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    job_id, created = repo.create_or_get(make_job())
    assert (job_id, created) == ("job-1", True)
    again, created_again = repo.create_or_get(make_job("job-2"))
    assert (again, created_again) == ("job-1", False)
    assert repo.status_of("job-1") == "DISCOVERING"


def test_a_different_selection_creates_a_second_job(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    other, created = repo.create_or_get(make_job("job-2", courses=["560"]))
    assert (other, created) == ("job-2", True)


def test_claiming_leases_the_job_and_a_second_worker_gets_nothing(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    claimed = repo.claim(worker_id="w1")
    assert claimed is not None
    assert claimed.course_ids == ("240", "560")
    assert repo.claim(worker_id="w2") is None, "a leased job must not be claimed twice"


def test_an_expired_lease_is_claimable_again(tmp_path) -> None:
    """The property that makes a crashed worker recoverable rather than fatal."""
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    repo.claim(worker_id="w1")
    later = datetime.now(UTC) + timedelta(seconds=600)
    reclaimed = repo.claim(worker_id="w2", now=later)
    assert reclaimed is not None and reclaimed.job_id == "job-1"


def test_a_terminal_job_is_never_claimed_again(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    repo.set_status("job-1", "COMPLETED")
    assert repo.claim(worker_id="w1") is None
    assert repo.status_of("job-1") == "COMPLETED"


def test_setting_a_terminal_status_releases_the_lease_and_stamps_completion(tmp_path) -> None:
    repo, connection = repository(tmp_path)
    repo.create_or_get(make_job())
    repo.claim(worker_id="w1")
    repo.set_status("job-1", "COMPLETED_WITH_WARNINGS", error_code="FORBIDDEN")
    row = connection.execute(
        "SELECT leased_until, worker_id, completed_at, error_code FROM canvas_import_jobs "
        "WHERE id='job-1'"
    ).fetchone()
    assert row["leased_until"] is None and row["worker_id"] is None
    assert row["completed_at"] is not None
    assert row["error_code"] == "FORBIDDEN"


def test_releasing_a_lease_keeps_the_status(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    repo.claim(worker_id="w1")
    repo.set_status("job-1", "DOWNLOADING")
    repo.release("job-1")
    assert repo.status_of("job-1") == "DOWNLOADING"
    assert repo.claim(worker_id="w2") is not None


def test_an_invented_status_is_refused(tmp_path) -> None:
    repo, _ = repository(tmp_path)
    repo.create_or_get(make_job())
    try:
        repo.set_status("job-1", "DONE")
    except JobStateError:
        return
    raise AssertionError("an unknown status was accepted")


def test_file_rows_are_keyed_by_external_identity(tmp_path) -> None:
    repo, connection = repository(tmp_path)
    repo.create_or_get(make_job())
    first = repo.upsert_file(
        "job-1", origin=CITYU, course_id="560", file_id="1", display_name="a.pdf", size=10
    )
    # Same name, different Canvas id → a separate row, not an overwrite.
    second = repo.upsert_file(
        "job-1", origin=CITYU, course_id="560", file_id="2", display_name="a.pdf", size=20
    )
    assert first != second
    # Same identity again → the same row, updated in place.
    assert (
        repo.upsert_file(
            "job-1", origin=CITYU, course_id="560", file_id="1", display_name="a.pdf", size=99
        )
        == first
    )
    rows = connection.execute(
        "SELECT source_file_id, size_bytes, status FROM canvas_import_files ORDER BY source_file_id"
    ).fetchall()
    assert [(r["source_file_id"], r["size_bytes"]) for r in rows] == [("1", 99), ("2", 20)]
    assert all(r["status"] == "PENDING" for r in rows)


def test_the_database_never_stores_a_token_even_after_a_full_job(tmp_path) -> None:
    repo, connection = repository(tmp_path)
    repo.create_or_get(make_job())
    repo.claim(worker_id="w1")
    repo.upsert_file(
        "job-1", origin=CITYU, course_id="560", file_id="1", display_name="a.pdf", size=10
    )
    repo.set_status("job-1", "COMPLETED")
    for table in ("canvas_connections", "canvas_import_jobs", "canvas_import_files"):
        dump = "\n".join(str(row) for row in connection.execute(f"SELECT * FROM {table}"))
        for forbidden in ("Bearer ", "access_token", "refresh_token", "client_secret"):
            assert forbidden not in dump, f"{table} contains {forbidden}"
