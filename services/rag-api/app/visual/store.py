from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.db import Database

ACTIVE = {"QUEUED", "PLANNING", "RENDERING", "VALIDATING", "RETRYING"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
TRANSITIONS = {
    "QUEUED": {"PLANNING", "FAILED", "CANCELLED"},
    "PLANNING": {"RENDERING", "VALIDATING", "FAILED", "CANCELLED"},
    "RENDERING": {"VALIDATING", "FAILED", "CANCELLED"},
    "VALIDATING": {"COMPLETED", "FAILED", "CANCELLED"},
    "FAILED": {"RETRYING"},
    "RETRYING": {"PLANNING", "RENDERING", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


class IdempotencyConflict(RuntimeError):
    pass


class VisualStateConflict(RuntimeError):
    pass


class VisualStoreQuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class VisualJobCreate:
    request_id: str
    request_hash: str
    user_id: str
    course_id: str
    pair_id: str
    message_id: str
    node_id: str | None
    action: str
    source_snapshot_hash: str
    frozen_input_json: str
    prompt_version: str
    prompt_hash: str
    provider: str = "mock"
    parent_job_id: str | None = None
    retry_count: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, object] | None:
    return dict(row) if row is not None else None


class VisualJobStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        value: VisualJobCreate,
        *,
        max_user_active: int | None = None,
        max_global_active: int | None = None,
    ) -> tuple[dict[str, object], bool]:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM visual_jobs WHERE user_id=? AND request_id=?",
                (value.user_id, value.request_id),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != value.request_hash:
                    raise IdempotencyConflict("request_id was already bound to another payload")
                return dict(existing), False
            if max_user_active is not None or max_global_active is not None:
                placeholders = ",".join("?" for _ in ACTIVE)
                states = tuple(sorted(ACTIVE))
                if max_user_active is not None:
                    user_active = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM visual_jobs WHERE user_id=? "
                            f"AND status IN ({placeholders})",
                            (value.user_id, *states),
                        ).fetchone()[0]
                    )
                    if user_active >= max_user_active:
                        raise VisualStoreQuotaExceeded("per-user concurrent visual quota exceeded")
                if max_global_active is not None:
                    global_active = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM visual_jobs WHERE status IN ({placeholders})",
                            states,
                        ).fetchone()[0]
                    )
                    if global_active >= max_global_active:
                        raise VisualStoreQuotaExceeded("global concurrent visual quota exceeded")
            job_id = "visual-job-" + uuid4().hex
            connection.execute(
                """
                INSERT INTO visual_jobs(
                    id,parent_job_id,request_id,request_hash,user_id,course_id,pair_id,
                    message_id,node_id,action,source_snapshot_hash,frozen_input_json,
                    prompt_version,prompt_hash,provider,status,retry_count,queue_at,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'QUEUED',?,?,?,?)
                """,
                (
                    job_id,
                    value.parent_job_id,
                    value.request_id,
                    value.request_hash,
                    value.user_id,
                    value.course_id,
                    value.pair_id,
                    value.message_id,
                    value.node_id,
                    value.action,
                    value.source_snapshot_hash,
                    value.frozen_input_json,
                    value.prompt_version,
                    value.prompt_hash,
                    value.provider,
                    value.retry_count,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            self._event(connection, job_id, 0, "CREATED", None, "QUEUED", {})
            created = connection.execute(
                "SELECT * FROM visual_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return dict(created), True

    def get(self, job_id: str, *, user_id: str | None = None) -> dict[str, object] | None:
        query = "SELECT * FROM visual_jobs WHERE id=?"
        params: tuple[object, ...] = (job_id,)
        if user_id is not None:
            query += " AND user_id=?"
            params += (user_id,)
        with self.database.connect() as connection:
            return _row(connection.execute(query, params).fetchone())

    def get_by_request(self, user_id: str, request_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            return _row(
                connection.execute(
                    "SELECT * FROM visual_jobs WHERE user_id=? AND request_id=?",
                    (user_id, request_id),
                ).fetchone()
            )

    def get_assistance_preference(self, user_id: str, course_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM visual_assistance_preferences WHERE user_id=? AND course_id=?",
                (user_id, course_id),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "course_id": course_id,
                "enabled": False,
                "consent_version": "visual-assistance-v1",
                "enabled_at": None,
                "updated_at": None,
            }
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        return value

    def set_assistance_preference(
        self,
        user_id: str,
        course_id: str,
        *,
        enabled: bool,
        consent_version: str,
        request_id: str,
    ) -> tuple[dict[str, object], bool]:
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "user_id": user_id,
                    "course_id": course_id,
                    "enabled": enabled,
                    "consent_version": consent_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM visual_assistance_preferences WHERE user_id=? AND course_id=?",
                (user_id, course_id),
            ).fetchone()
            if current is not None and current["last_request_id"] == request_id:
                if current["last_request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "request_id was already bound to another preference payload"
                    )
                result = dict(current)
                result["enabled"] = bool(result["enabled"])
                return result, False
            enabled_at = timestamp if enabled else (current["enabled_at"] if current else None)
            if current is None:
                connection.execute(
                    "INSERT INTO visual_assistance_preferences("
                    "user_id,course_id,enabled,consent_version,enabled_at,last_request_id,"
                    "last_request_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        course_id,
                        int(enabled),
                        consent_version,
                        enabled_at,
                        request_id,
                        request_hash,
                        timestamp,
                        timestamp,
                    ),
                )
                created = True
            else:
                connection.execute(
                    "UPDATE visual_assistance_preferences SET enabled=?,consent_version=?,"
                    "enabled_at=?,last_request_id=?,last_request_hash=?,updated_at=? "
                    "WHERE user_id=? AND course_id=?",
                    (
                        int(enabled),
                        consent_version,
                        enabled_at,
                        request_id,
                        request_hash,
                        timestamp,
                        user_id,
                        course_id,
                    ),
                )
                created = False
            result = dict(
                connection.execute(
                    "SELECT * FROM visual_assistance_preferences WHERE user_id=? AND course_id=?",
                    (user_id, course_id),
                ).fetchone()
            )
            result["enabled"] = bool(result["enabled"])
            return result, created

    def daily_completed_counts(self, user_id: str, day_prefix: str) -> tuple[int, int, float]:
        with self.database.connect() as connection:
            image_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM visual_jobs WHERE user_id=? AND status='COMPLETED' "
                    "AND renderer<>'COMFY_VIDEO' AND created_at LIKE ?",
                    (user_id, day_prefix + "%"),
                ).fetchone()[0]
            )
            video_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM visual_jobs WHERE user_id=? AND status='COMPLETED' "
                    "AND renderer='COMFY_VIDEO' AND created_at LIKE ?",
                    (user_id, day_prefix + "%"),
                ).fetchone()[0]
            )
            gpu_seconds = float(
                connection.execute(
                    "SELECT COALESCE(SUM(gpu_seconds),0) FROM visual_jobs "
                    "WHERE user_id=? AND created_at LIKE ?",
                    (user_id, day_prefix + "%"),
                ).fetchone()[0]
            )
        return image_count, video_count, gpu_seconds

    def list_for_message(
        self, user_id: str, course_id: str, message_id: str
    ) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            newest = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM visual_jobs WHERE user_id=? AND course_id=? AND message_id=? "
                    "ORDER BY created_at DESC,rowid DESC LIMIT 100",
                    (user_id, course_id, message_id),
                )
            ]
        return list(reversed(newest))

    def list_for_pair(self, user_id: str, course_id: str, pair_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            newest = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM visual_jobs WHERE user_id=? AND course_id=? AND pair_id=? "
                    "ORDER BY created_at DESC,rowid DESC LIMIT 100",
                    (user_id, course_id, pair_id),
                )
            ]
        return list(reversed(newest))

    def claim_next(
        self, worker_id: str, *, now_epoch: float, lease_seconds: float
    ) -> dict[str, object] | None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                """
                SELECT * FROM visual_jobs
                WHERE status IN ('QUEUED','PLANNING','RENDERING','VALIDATING','RETRYING')
                  AND cancel_requested=0
                  AND (lease_owner IS NULL OR lease_expires_at < ?)
                ORDER BY priority DESC, queue_at, id LIMIT 1
                """,
                (now_epoch,),
            ).fetchone()
            if job is None:
                return None
            connection.execute(
                "UPDATE visual_jobs SET lease_owner=?,lease_expires_at=?,"
                "attempt_count=attempt_count+1,"
                "started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
                (worker_id, now_epoch + lease_seconds, _now(), _now(), job["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM visual_jobs WHERE id=?", (job["id"],)
            ).fetchone()
            self._event(
                connection,
                str(job["id"]),
                int(claimed["attempt_count"]),
                "CLAIMED",
                str(job["status"]),
                str(job["status"]),
                {"worker": worker_id},
            )
            return dict(claimed)

    def renew_lease(self, job_id: str, worker_id: str, *, expires_at: float) -> bool:
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE visual_jobs SET lease_expires_at=?,updated_at=? "
                "WHERE id=? AND lease_owner=? AND status NOT IN ('COMPLETED','FAILED','CANCELLED')",
                (expires_at, _now(), job_id, worker_id),
            ).rowcount
            return changed == 1

    def transition(
        self,
        job_id: str,
        target: str,
        *,
        expected: Iterable[str] | None = None,
        fields: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM visual_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if current is None:
                raise KeyError(job_id)
            current_status = str(current["status"])
            allowed_expected = set(expected) if expected is not None else {current_status}
            if current_status not in allowed_expected or target not in TRANSITIONS[current_status]:
                raise VisualStateConflict(f"illegal visual transition {current_status}->{target}")
            if current["cancel_requested"] and target != "CANCELLED":
                raise VisualStateConflict("cancelled visual jobs cannot publish late results")
            updates = {"status": target, "updated_at": _now(), **(fields or {})}
            if target in TERMINAL:
                updates["completed_at"] = _now()
                updates["lease_owner"] = None
                updates["lease_expires_at"] = None
            columns = ",".join(f"{name}=?" for name in updates)
            connection.execute(
                f"UPDATE visual_jobs SET {columns} WHERE id=?",
                (*updates.values(), job_id),
            )
            self._event(
                connection,
                job_id,
                int(current["attempt_count"]),
                "STATE",
                current_status,
                target,
                {"error_code": updates.get("error_code")},
            )
            return dict(
                connection.execute("SELECT * FROM visual_jobs WHERE id=?", (job_id,)).fetchone()
            )

    def patch(self, job_id: str, fields: dict[str, object]) -> dict[str, object]:
        if not fields:
            current = self.get(job_id)
            if current is None:
                raise KeyError(job_id)
            return current
        allowed = {
            "visual_spec_json",
            "visual_spec_version",
            "visual_spec_hash",
            "renderer",
            "provider_job_id",
            "workflow_id",
            "workflow_version",
            "cache_key",
            "model_version",
            "error_code",
            "error_detail_safe",
            "estimated_cost_micros",
            "actual_cost_micros",
            "cost_currency",
            "gpu_seconds",
            "cache_hit",
            "output_bytes",
            "renderer_wait_started_at",
            "renderer_ready_at",
            "renderer_wait_seconds",
        }
        if set(fields) - allowed:
            raise ValueError("Visual job patch contains unsupported fields")
        updates = {**fields, "updated_at": _now()}
        columns = ",".join(f"{name}=?" for name in updates)
        with self.database.connect() as connection:
            changed = connection.execute(
                f"UPDATE visual_jobs SET {columns} WHERE id=?",
                (*updates.values(), job_id),
            ).rowcount
            if changed != 1:
                raise KeyError(job_id)
            return dict(
                connection.execute("SELECT * FROM visual_jobs WHERE id=?", (job_id,)).fetchone()
            )

    def cancel(self, job_id: str, user_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM visual_jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            if job["status"] in TERMINAL:
                return dict(job)
            timestamp = _now()
            connection.execute(
                "UPDATE visual_jobs SET status='CANCELLED',cancel_requested=1,completed_at=?,"
                "lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",
                (timestamp, timestamp, job_id),
            )
            self._event(
                connection,
                job_id,
                int(job["attempt_count"]),
                "CANCELLED",
                str(job["status"]),
                "CANCELLED",
                {},
            )
            return dict(
                connection.execute("SELECT * FROM visual_jobs WHERE id=?", (job_id,)).fetchone()
            )

    def cache_get(self, cache_key: str, scope_key: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT a.* FROM visual_cache_entries c JOIN visual_assets a ON a.id=c.asset_id "
                "WHERE c.cache_key=? AND c.scope_key=?",
                (cache_key, scope_key),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE visual_cache_entries SET last_used_at=? WHERE cache_key=?",
                (_now(), cache_key),
            )
            return dict(row)

    def cache_put(
        self,
        *,
        cache_key: str,
        asset_id: str,
        scope_key: str,
        course_id: str,
        source_snapshot_hash: str,
        visual_spec_hash: str,
        renderer: str,
        renderer_version: str,
        prompt_version: str,
        workflow_id: str,
        workflow_version: str,
        model_version: str,
        language: str,
    ) -> None:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO visual_cache_entries(cache_key,asset_id,scope_key,course_id,"
                "source_snapshot_hash,visual_spec_hash,renderer,renderer_version,prompt_version,"
                "workflow_id,workflow_version,model_version,language,created_at,last_used_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cache_key,
                    asset_id,
                    scope_key,
                    course_id,
                    source_snapshot_hash,
                    visual_spec_hash,
                    renderer,
                    renderer_version,
                    prompt_version,
                    workflow_id,
                    workflow_version,
                    model_version,
                    language,
                    timestamp,
                    timestamp,
                ),
            )

    def create_asset(self, values: dict[str, object]) -> dict[str, object]:
        payload = dict(values)
        asset_id = str(payload.pop("id", None) or ("visual-asset-" + uuid4().hex))
        columns = ["id", *payload.keys()]
        params = [asset_id, *payload.values()]
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM visual_assets WHERE id=?", (asset_id,)
            ).fetchone()
            if existing is not None:
                trusted = {"origin_job_id", "user_id", "course_id", "storage_key", "sha256"}
                if any(str(existing[key]) != str(payload[key]) for key in trusted):
                    raise IdempotencyConflict("visual asset ID was already bound to other bytes")
                return dict(existing)
            connection.execute(
                f"INSERT INTO visual_assets({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                params,
            )
            return dict(
                connection.execute("SELECT * FROM visual_assets WHERE id=?", (asset_id,)).fetchone()
            )

    def link_asset(self, job_id: str, asset_id: str, *, role: str = "primary") -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO visual_job_assets"
                "(job_id,asset_id,role,created_at) VALUES(?,?,?,?)",
                (job_id, asset_id, role, _now()),
            )

    def assets_for_job(self, job_id: str, *, user_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT a.* FROM visual_job_assets ja JOIN visual_assets a ON a.id=ja.asset_id "
                    "JOIN visual_jobs j ON j.id=ja.job_id "
                    "WHERE ja.job_id=? AND j.user_id=? ORDER BY ja.created_at",
                    (job_id, user_id),
                )
            ]

    def get_asset(self, asset_id: str, *, user_id: str) -> dict[str, object] | None:
        with self.database.connect() as connection:
            return _row(
                connection.execute(
                    "SELECT DISTINCT a.* FROM visual_assets a "
                    "JOIN visual_job_assets ja ON ja.asset_id=a.id "
                    "JOIN visual_jobs j ON j.id=ja.job_id "
                    "WHERE a.id=? AND j.user_id=?",
                    (asset_id, user_id),
                ).fetchone()
            )

    @staticmethod
    def cache_key(**values: str) -> str:
        raw = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _event(
        connection: object,
        job_id: str,
        attempt: int,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        detail: dict[str, object],
    ) -> None:
        connection.execute(  # type: ignore[attr-defined]
            "INSERT INTO visual_job_events(job_id,attempt,event_type,from_status,to_status,"
            "safe_detail_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                job_id,
                attempt,
                event_type,
                from_status,
                to_status,
                json.dumps(detail, sort_keys=True),
                _now(),
            ),
        )
