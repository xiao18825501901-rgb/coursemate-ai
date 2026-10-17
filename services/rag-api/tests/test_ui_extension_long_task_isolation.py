from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from app.ui_extension.domain import V3DomainAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "method_name", "payload"),
    [
        ("file.upload", "_file_upload", {"course": "course-a"}),
        (
            "context.retrieve",
            "_retrieve",
            {"course": "course-a", "query": "degree"},
        ),
    ],
)
async def test_long_rag_work_does_not_block_the_online_event_loop(
    operation: str,
    method_name: str,
    payload: dict[str, Any],
) -> None:
    """Slow parsing, indexing, or retrieval must not pause unrelated online work."""

    adapter = object.__new__(V3DomainAdapter)
    adapter._begin_request = lambda: None  # type: ignore[method-assign]
    adapter._course_row = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]

    order: list[str] = []

    def slow_upload(_subject: str, _payload: dict[str, Any]) -> dict[str, str]:
        order.append("upload-started")
        time.sleep(0.25)
        order.append("upload-finished")
        return {"status": "ready"}

    setattr(adapter, method_name, slow_upload)

    async def online_heartbeat() -> None:
        await asyncio.sleep(0)
        order.append("online-heartbeat")

    upload_result, _ = await asyncio.gather(
        adapter._dispatch(operation, "student", payload),
        online_heartbeat(),
    )

    assert upload_result == {"status": "ready"}
    assert order.index("online-heartbeat") < order.index("upload-finished")
