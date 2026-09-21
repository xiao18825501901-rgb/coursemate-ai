"""Structured logging with a hard privacy boundary.

CourseMate-internal service: student answers, private material, plans and
credentials are NEVER logged. Logs contain only ids, hashes, lengths, timings
and error codes/types. There is deliberately no helper that logs a request or
response body, so nothing sensitive can leak by accident.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

# Request ids must be a short, safe token before we will echo them into logs.
# This closes the log-forgery vector where a client injects newlines / control
# chars into a free-text id that is then written verbatim.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_LOGGER = logging.getLogger("laya")


def safe_id(value: str) -> str:
    """Validate a client-supplied id for logging; returns the value or raises ValueError."""
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise ValueError("id must match [A-Za-z0-9._:-]{1,128}")
    return value


class _JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields are injected as a sanitized ``data`` map."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data = getattr(record, "data", None)
        if isinstance(data, dict):
            payload["data"] = data
        if record.exc_info and record.exc_info[0] is not None:
            # Type only: exception *messages* may embed request content.
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, separators=(",", ":"))


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = getattr(record, "data", None)
        suffix = f" {json.dumps(data, separators=(',', ':'))}" if isinstance(data, dict) else ""
        base = super().format(record)
        return f"{base}{suffix}"


def configure_logging(log_level: str, log_format: str) -> None:
    """Install the service logger (stdout, no propagation surprises)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if log_format == "json" else _TextFormatter())
    root = logging.getLogger("laya")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, str(log_level).upper(), logging.INFO))
    root.propagate = False


def log_request(
    *,
    request_id: str,
    receipt_id: str,
    definition_id: str | None,
    definition_version: str | None,
    status: str,
    http_status: int,
    tokens: int | None,
    state_len: int | None,
    duration_ms: float,
    error_code: str | None,
) -> None:
    """Emit the single per-request audit line. Scalars only, no content."""
    _LOGGER.info(
        "decision %s",
        receipt_id,
        extra={
            "data": {
                "request_id": request_id,
                "receipt_id": receipt_id,
                "definition_id": definition_id,
                "definition_version": definition_version,
                "status": status,
                "http_status": http_status,
                "input_tokens": tokens,
                "state_len": state_len,
                "duration_ms": round(duration_ms, 3),
                "error_code": error_code,
            }
        },
    )
