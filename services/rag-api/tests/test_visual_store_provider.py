from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import LATEST_V3_SCHEMA_VERSION, Database
from app.visual.providers.base import ProviderState
from app.visual.providers.mock_comfy import MockComfyProvider
from app.visual.store import (
    IdempotencyConflict,
    VisualJobCreate,
    VisualJobStore,
    VisualStateConflict,
    VisualStoreQuotaExceeded,
)
from app.visual.validators import InvalidVisualOutput, validate_output


def database_at(tmp_path: Path) -> Database:
    database = Database(
        Settings(
            _env_file=None,
            app_env="test",
            rag_provider_mode="deterministic",
            v3_enabled=True,
            database_path=tmp_path / "rag.sqlite3",
            upload_dir=tmp_path / "uploads",
            storage_cache_dir=tmp_path / "cache",
        )
    )
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO courses(id,name,owner_user_id,course_type,visibility) "
            "VALUES('course-1','Course','user-1','user','private')"
        )
    return database


def create_input(**changes: object) -> VisualJobCreate:
    values: dict[str, object] = {
        "request_id": "request-1",
        "request_hash": "a" * 64,
        "user_id": "user-1",
        "course_id": "course-1",
        "pair_id": "pair-1",
        "message_id": "message-1",
        "node_id": None,
        "action": "diagram",
        "source_snapshot_hash": "b" * 64,
        "frozen_input_json": '{"answer":"grounded"}',
        "prompt_version": "visual-router-planner-v1",
        "prompt_hash": "c" * 64,
    }
    values.update(changes)
    return VisualJobCreate(**values)


def test_visual_migration_is_current_and_replay_safe(tmp_path: Path) -> None:
    database = database_at(tmp_path)
    database.initialize()
    with database.connect() as connection:
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == LATEST_V3_SCHEMA_VERSION
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(visual_jobs)").fetchall()
        }
        assert {
            "renderer_wait_started_at",
            "renderer_ready_at",
            "renderer_wait_seconds",
        } <= columns
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'visual_%'"
            )
        }
    assert {
        "visual_jobs",
        "visual_assets",
        "visual_cache_entries",
        "visual_job_events",
        "visual_assistance_preferences",
    } <= tables


def test_visual_assistance_defaults_off_and_is_idempotently_persisted(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    default = store.get_assistance_preference("user-1", "course-1")
    assert default["enabled"] is False
    assert default["consent_version"] == "visual-assistance-v1"

    enabled, created = store.set_assistance_preference(
        "user-1",
        "course-1",
        enabled=True,
        consent_version="visual-assistance-v1",
        request_id="preference-request-1",
    )
    replay, replay_created = store.set_assistance_preference(
        "user-1",
        "course-1",
        enabled=True,
        consent_version="visual-assistance-v1",
        request_id="preference-request-1",
    )
    assert created is True
    assert replay_created is False
    assert enabled == replay
    assert enabled["enabled"] is True
    assert enabled["enabled_at"]

    with pytest.raises(IdempotencyConflict):
        store.set_assistance_preference(
            "user-1",
            "course-1",
            enabled=False,
            consent_version="visual-assistance-v1",
            request_id="preference-request-1",
        )


def test_visual_assistance_is_scoped_to_user_and_course(tmp_path: Path) -> None:
    database = database_at(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO courses(id,name,owner_user_id,course_type,visibility) "
            "VALUES('course-2','Other','user-1','user','private')"
        )
    store = VisualJobStore(database)
    store.set_assistance_preference(
        "user-1",
        "course-1",
        enabled=True,
        consent_version="visual-assistance-v1",
        request_id="preference-request-2",
    )
    assert store.get_assistance_preference("user-1", "course-1")["enabled"] is True
    assert store.get_assistance_preference("user-1", "course-2")["enabled"] is False
    assert store.get_assistance_preference("user-2", "course-1")["enabled"] is False


def test_create_is_idempotent_but_rejects_changed_payload(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    first, created = store.create(create_input())
    replay, replay_created = store.create(create_input())
    assert created is True
    assert replay_created is False
    assert replay["id"] == first["id"]
    with pytest.raises(IdempotencyConflict):
        store.create(create_input(request_hash="d" * 64))


def test_active_job_quota_is_checked_inside_the_create_transaction(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    store.create(create_input(), max_user_active=1, max_global_active=1)
    with pytest.raises(VisualStoreQuotaExceeded, match="concurrent"):
        store.create(
            create_input(request_id="request-2", request_hash="d" * 64),
            max_user_active=1,
            max_global_active=1,
        )


def test_claim_is_atomic_and_stale_lease_is_recovered(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    job, _ = store.create(create_input())
    claimed = store.claim_next("worker-1", now_epoch=100, lease_seconds=10)
    assert claimed is not None and claimed["id"] == job["id"]
    assert store.claim_next("worker-2", now_epoch=105, lease_seconds=10) is None
    recovered = store.claim_next("worker-2", now_epoch=111, lease_seconds=10)
    assert recovered is not None and recovered["id"] == job["id"]
    assert recovered["lease_owner"] == "worker-2"


def test_cancel_is_durable_and_late_completion_is_suppressed(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    job, _ = store.create(create_input())
    store.claim_next("worker", now_epoch=100, lease_seconds=30)
    store.transition(job["id"], "PLANNING", expected={"QUEUED"})
    cancelled = store.cancel(job["id"], "user-1")
    assert cancelled["status"] == "CANCELLED"
    with pytest.raises(VisualStateConflict):
        store.transition(job["id"], "COMPLETED", expected={"VALIDATING"})


def test_private_cache_is_owner_scoped_and_version_sensitive(tmp_path: Path) -> None:
    store = VisualJobStore(database_at(tmp_path))
    first = store.cache_key(
        course_id="course-1",
        source_snapshot_hash="s1",
        visual_spec_hash="v1",
        renderer="SVG",
        renderer_version="1",
        prompt_version="p1",
        workflow_id="deterministic-svg",
        workflow_version="1",
        model_version="none",
        language="en",
        scope_key="private:user-1",
    )
    same = store.cache_key(
        course_id="course-1",
        source_snapshot_hash="s1",
        visual_spec_hash="v1",
        renderer="SVG",
        renderer_version="1",
        prompt_version="p1",
        workflow_id="deterministic-svg",
        workflow_version="1",
        model_version="none",
        language="en",
        scope_key="private:user-1",
    )
    other_owner = store.cache_key(
        course_id="course-1",
        source_snapshot_hash="s1",
        visual_spec_hash="v1",
        renderer="SVG",
        renderer_version="1",
        prompt_version="p1",
        workflow_id="deterministic-svg",
        workflow_version="1",
        model_version="none",
        language="en",
        scope_key="private:user-2",
    )
    other_source = first[:-1] + ("0" if first[-1] != "0" else "1")
    assert first == same
    assert first != other_owner
    assert first != other_source


def test_mock_provider_modes_and_idempotency() -> None:
    provider = MockComfyProvider()
    first = provider.submit({}, idempotency_key="success")
    assert provider.submit({}, idempotency_key="success").id == first.id
    assert provider.get_status(first.id).state is ProviderState.RUNNING
    assert provider.get_status(first.id).state is ProviderState.COMPLETED
    result = provider.get_result(first.id)
    assert result.mime_type == "image/png"
    assert result.content.startswith(b"\x89PNG")

    provider.set_mode("failure", "fail")
    failed = provider.submit({}, idempotency_key="failure")
    assert provider.get_status(failed.id).state is ProviderState.FAILED

    provider.set_mode("unknown", "unknown")
    unknown = provider.submit({}, idempotency_key="unknown")
    assert provider.get_status(unknown.id).state is ProviderState.UNKNOWN

    cancelled = provider.submit({}, idempotency_key="cancel")
    provider.cancel(cancelled.id)
    assert provider.get_status(cancelled.id).state is ProviderState.CANCELLED


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://attacker.invalid/x"/></svg>',
        b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
    ],
)
def test_svg_validation_rejects_active_or_external_content(unsafe_svg: bytes) -> None:
    with pytest.raises(InvalidVisualOutput):
        validate_output(
            unsafe_svg,
            mime_type="image/svg+xml",
            width=100,
            height=100,
            duration_seconds=None,
            max_bytes=10_000,
            max_width=200,
            max_height=200,
            max_duration_seconds=15,
        )
