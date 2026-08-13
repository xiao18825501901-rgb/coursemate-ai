#!/usr/bin/env python3
"""Emit a secret-free CourseMate production readiness snapshot for an external monitor."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REQUIRED_BACKUP_ARTIFACTS = {
    "SHA256SUMS",
    "agent.sqlite3",
    "manifest.json",
    "rag.sqlite3",
    "sqlite-check.txt",
    "uploads.tar.gz",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    latency_ms: int | None = None


def _positive_number(name: str, default: float) -> float:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number.") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return value


def check_health(name: str, url: str, expected_service: str, timeout: float) -> Check:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return Check(name, False, "health URL format is invalid")
    allow_insecure = os.environ.get("ALLOW_INSECURE_HEALTH_URLS") == "1"
    if parsed.scheme != "https" and not (allow_insecure and parsed.scheme == "http"):
        return Check(name, False, "health URL must use HTTPS")
    if (
        any(ord(character) < 32 or ord(character) == 127 for character in url)
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return Check(name, False, "health URL format is invalid")

    try:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "CourseMateMonitor/2"},
        )
    except ValueError:
        return Check(name, False, "health URL format is invalid")
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            payload: Any = json.loads(response.read(4096))
    except HTTPError as error:
        return Check(name, False, f"health returned HTTP {error.code}")
    except (URLError, TimeoutError, OSError, ValueError):
        return Check(name, False, "health request failed")
    except json.JSONDecodeError:
        return Check(name, False, "health response was not JSON")
    latency_ms = round((time.perf_counter() - started) * 1_000)
    if status_code != 200:
        return Check(name, False, f"health returned HTTP {status_code}", latency_ms)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return Check(name, False, "health response status was not ok", latency_ms)
    if payload.get("service") != expected_service:
        return Check(name, False, "health response service did not match", latency_ms)
    return Check(name, True, "healthy", latency_ms)


def check_backup(backup_root: Path, max_age: timedelta, now: datetime) -> Check:
    if not backup_root.is_dir():
        return Check("backup", False, "backup root is unavailable")
    candidates: list[tuple[datetime, Path]] = []
    try:
        backup_entries = list(backup_root.iterdir())
    except OSError:
        return Check("backup", False, "backup root could not be inspected")
    for candidate in backup_entries:
        if (
            candidate.is_symlink()
            or not candidate.is_dir()
            or not candidate.name.startswith("coursemate-v2-")
        ):
            continue
        try:
            artifacts = {path.name: path for path in candidate.iterdir()}
        except OSError:
            continue
        if not REQUIRED_BACKUP_ARTIFACTS.issubset(artifacts):
            continue
        if any(
            artifacts[name].is_symlink() or not artifacts[name].is_file()
            for name in REQUIRED_BACKUP_ARTIFACTS
        ):
            continue
        try:
            manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(str(manifest["createdAt"]))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
        if created_at.tzinfo is None:
            continue
        candidates.append((created_at.astimezone(UTC), candidate))
    if not candidates:
        return Check("backup", False, "no completed backup was found")
    created_at, _ = max(candidates, key=lambda item: item[0])
    age = now.astimezone(UTC) - created_at
    if age < -timedelta(minutes=5):
        return Check("backup", False, "latest backup timestamp is in the future")
    age_seconds = max(0, round(age.total_seconds()))
    if age > max_age:
        return Check("backup", False, f"latest backup is stale ({age_seconds}s old)")
    return Check("backup", True, f"latest backup age is {age_seconds}s")


def check_disk(path: Path, minimum_free_bytes: int) -> Check:
    if not path.is_dir():
        return Check("disk", False, "upload storage is unavailable")
    try:
        free_bytes = shutil.disk_usage(path).free
    except OSError:
        return Check("disk", False, "disk usage check failed")
    if free_bytes < minimum_free_bytes:
        return Check("disk", False, f"free space is below threshold ({free_bytes} bytes)")
    return Check("disk", True, f"free space is {free_bytes} bytes")


def main() -> int:
    try:
        timeout = _positive_number("HEALTH_TIMEOUT_SECONDS", 5)
        max_backup_age = timedelta(
            seconds=_positive_number("MAX_BACKUP_AGE_SECONDS", 93_600)
        )
        minimum_free_bytes = round(_positive_number("MIN_FREE_BYTES", 1_073_741_824))
    except ValueError as error:
        print(json.dumps({"status": "failing", "checks": [asdict(Check("config", False, str(error)))]}))
        return 2

    configured = {
        "rag": (os.environ.get("RAG_HEALTH_URL", ""), "rag-api"),
        "agent": (os.environ.get("AGENT_HEALTH_URL", ""), "agent-api"),
    }
    checks = [
        Check(name, False, "health URL is not configured")
        if not url
        else check_health(name, url, service, timeout)
        for name, (url, service) in configured.items()
    ]
    backup_root = os.environ.get("BACKUP_ROOT", "").strip()
    upload_root = os.environ.get("RAG_UPLOAD_DIR", "").strip()
    checks.extend(
        (
            Check("backup", False, "backup root is not configured")
            if not backup_root
            else check_backup(Path(backup_root), max_backup_age, datetime.now(UTC)),
            Check("disk", False, "upload storage is not configured")
            if not upload_root
            else check_disk(Path(upload_root), minimum_free_bytes),
        )
    )
    status = "ok" if all(check.ok for check in checks) else "failing"
    print(json.dumps({"status": status, "checkedAt": datetime.now(UTC).isoformat(), "checks": [asdict(check) for check in checks]}))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
