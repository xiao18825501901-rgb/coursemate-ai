from __future__ import annotations

import asyncio
import logging

from app.visual.service import VisualService

LOGGER = logging.getLogger(__name__)


async def visual_worker_loop(
    service: VisualService,
    *,
    worker_id: str,
    poll_seconds: float,
) -> None:
    """Run independently from text learning; failures cannot escape the loop."""

    while True:
        try:
            result = await asyncio.to_thread(service.run_once, worker_id)
            if result is None:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Visual worker iteration failed")
            await asyncio.sleep(poll_seconds)
