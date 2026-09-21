"""Thread-confined inference engine.

CPU inference is never run on the asyncio event loop. A small pool of worker
threads (``concurrency``, default 1) pulls jobs from a bounded queue and runs
the model synchronously. The design guarantees three things the HTTP layer must
be able to rely on:

1. **Bounded queue** -- enqueueing into a full queue raises immediately, and the
   caller gets a typed ``QUEUE_FULL`` rejection instead of unbounded buffering.
2. **A deadline never frees the worker slot early** -- the worker runs the model
   to completion even if the deadline has passed, and only then discards the
   late result. The single slot is therefore never silently reused while CPU
   inference is still in flight.
3. **A late result is never delivered** -- every job owns its own outcome and
   completion event. A request that timed out is marked ``abandoned``; when the
   worker finishes it sets that job's own (now-unobserved) outcome to
   ``DEADLINE_EXCEEDED``. It can never overwrite a newer request's answer.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.model import DecisionModel

Clock = Callable[[], float]


@dataclass
class InferenceOutcome:
    status: str
    answers: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    timings: dict[str, float] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class _Job:
    state: Any
    questions: dict[str, Any]
    deadline: float
    request_id: str
    loop: asyncio.AbstractEventLoop
    enqueued_at: float
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: InferenceOutcome | None = None
    abandoned: bool = False
    started_at: float | None = None
    finished_at: float | None = None


class InferenceEngine:
    """Bounded, deadline-aware worker pool around a single DecisionModel."""

    def __init__(
        self,
        model: DecisionModel,
        *,
        concurrency: int = 1,
        queue_size: int = 8,
        clock: Clock = time.monotonic,
    ) -> None:
        self._model = model
        self._concurrency = concurrency
        self._clock = clock
        self._queue: queue.Queue[_Job] = queue.Queue(maxsize=queue_size)
        self._workers: list[threading.Thread] = []
        self._stop = threading.Event()
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        for i in range(self._concurrency):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"laya-infer-{i}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        for thread in self._workers:
            thread.join(timeout)
        self._workers.clear()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started and not self._stop.is_set()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # -- request path ------------------------------------------------------
    async def decide(
        self,
        state: Any,
        questions: dict[str, Any],
        deadline_ms: float,
        request_id: str,
    ) -> InferenceOutcome:
        if not self._started or self._stop.is_set():
            raise RuntimeError("engine not started")
        loop = asyncio.get_running_loop()
        now = self._clock()
        deadline = now + deadline_ms / 1000.0
        job = _Job(
            state=state,
            questions=questions,
            deadline=deadline,
            request_id=request_id,
            loop=loop,
            enqueued_at=now,
        )
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            return InferenceOutcome(
                status="QUEUE_FULL",
                timings={"queue_wait_ms": 0.0, "inference_ms": 0.0, "total_ms": 0.0},
            )

        remaining = deadline - self._clock()
        if remaining <= 0:
            job.abandoned = True
            return self._deadline_outcome(job)

        try:
            await asyncio.wait_for(job.done_event.wait(), timeout=remaining)
        except TimeoutError:
            job.abandoned = True
            return self._deadline_outcome(job)

        outcome = job.outcome or InferenceOutcome(status="INFERENCE_ERROR")
        outcome.timings["total_ms"] = round((self._clock() - job.enqueued_at) * 1000.0, 3)
        return outcome

    def _deadline_outcome(self, job: _Job) -> InferenceOutcome:
        return InferenceOutcome(
            status="DEADLINE_EXCEEDED",
            timings={
                "queue_wait_ms": round((job.started_at - job.enqueued_at) * 1000.0, 3)
                if job.started_at is not None
                else 0.0,
                "inference_ms": 0.0,
                "total_ms": round((self._clock() - job.enqueued_at) * 1000.0, 3),
            },
        )

    # -- worker ------------------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._run_job(job)
            finally:
                self._queue.task_done()

    def _run_job(self, job: _Job) -> None:
        """Run one job to completion; discard late results. Deterministic and
        directly unit-testable (the worker thread calls this)."""
        job.started_at = self._clock()
        if job.abandoned or self._clock() >= job.deadline:
            job.outcome = self._deadline_outcome(job)
            self._publish(job)
            return
        try:
            result = self._model.predict(job.state, job.questions)
            job.finished_at = self._clock()
            timings = {
                "queue_wait_ms": round((job.started_at - job.enqueued_at) * 1000.0, 3),
                "inference_ms": round((job.finished_at - job.started_at) * 1000.0, 3),
            }
            if job.abandoned or self._clock() > job.deadline:
                job.outcome = InferenceOutcome(
                    status="DEADLINE_EXCEEDED",
                    timings=timings,
                    error_message="late result discarded",
                )
            else:
                job.outcome = InferenceOutcome(
                    status="OK",
                    answers=result.get("answers") if isinstance(result, dict) else None,
                    usage=result.get("usage") if isinstance(result, dict) else None,
                    timings=timings,
                )
        except Exception as exc:  # noqa: BLE001 - surface type only, never content
            job.finished_at = self._clock()
            job.outcome = InferenceOutcome(
                status="INFERENCE_ERROR",
                timings={
                    "queue_wait_ms": round((job.started_at - job.enqueued_at) * 1000.0, 3),
                    "inference_ms": round((job.finished_at - job.started_at) * 1000.0, 3),
                },
                error_code="INFERENCE_ERROR",
                error_message=type(exc).__name__,
            )
        self._publish(job)

    @staticmethod
    def _publish(job: _Job) -> None:
        if job.loop is not None and not job.loop.is_closed():
            job.loop.call_soon_threadsafe(job.done_event.set)
