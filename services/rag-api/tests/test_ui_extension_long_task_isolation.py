from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from app.ui_extension.domain import V3DomainAdapter


@pytest.mark.asyncio
async def test_file_upload_processing_does_not_block_the_online_event_loop() -> None:
    """A slow parser/indexer must not pause unrelated online request work."""

    adapter = object.__new__(V3DomainAdapter)
    adapter._begin_request = lambda: None  # type: ignore[method-assign]
    adapter._course_row = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]

    order: list[str] = []

    def slow_upload(_subject: str, _payload: dict[str, Any]) -> dict[str, str]:
        order.append("upload-started")
        time.sleep(0.25)
        order.append("upload-finished")
        return {"status": "ready"}

    adapter._file_upload = slow_upload  # type: ignore[method-assign]

    async def online_heartbeat() -> None:
        await asyncio.sleep(0)
        order.append("online-heartbeat")

    upload_result, _ = await asyncio.gather(
        adapter._dispatch("file.upload", "student", {"course": "course-a"}),
        online_heartbeat(),
    )

    assert upload_result == {"status": "ready"}
    assert order.index("online-heartbeat") < order.index("upload-finished")
