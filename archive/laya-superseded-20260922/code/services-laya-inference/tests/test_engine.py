"""Engine: concurrency, bounded queue, and deadline/discard semantics.

All tests use the fake model with sleep/clock injection; no torch, no network.
"""

from __future__ import annotations

import asyncio
import threading
import time

from app.engine import InferenceEngine, _Job

from tests.fake_agent import ManualClock, make_fake, noul_result

NOUL = {"q": {"type": "noul", "instructions": "x"}}


def test_queue_full_rejects_immediately() -> None:
    entered = threading.Event()
    release = threading.Event()
    model = make_fake(
        predict_fn=_blocking_predict(entered, release, block_on="__BLOCK__")
    )
    engine = InferenceEngine(model, concurrency=1, queue_size=1)
    engine.start()

    async def scenario() -> str:
        a = asyncio.create_task(engine.decide("__BLOCK__", NOUL, 60_000, "a"))
        assert await asyncio.to_thread(entered.wait, 5) is True
        b = asyncio.create_task(engine.decide("B", NOUL, 60_000, "b"))
        await asyncio.sleep(0.05)  # let B enqueue into the single queue slot
        c = await engine.decide("C", NOUL, 60_000, "c")
        assert c.status == "QUEUE_FULL"
        release.set()
        await a
        await b
        return c.status

    assert asyncio.run(scenario()) == "QUEUE_FULL"
    engine.stop()


def test_deadline_exceeded_discards_late_result() -> None:
    def slow(state, questions):
        time.sleep(0.2)
        return noul_result()

    model = make_fake(predict_fn=slow)
    engine = InferenceEngine(model, concurrency=1, queue_size=2)
    engine.start()
    res = asyncio.run(engine.decide("s", NOUL, 50, "r"))
    assert res.status == "DEADLINE_EXCEEDED"
    assert res.answers is None
    engine.stop()


def test_slot_not_freed_while_inference_running() -> None:
    entered_a = threading.Event()
    release_a = threading.Event()
    b_started = threading.Event()

    def predict_fn(state, questions):
        if state == "A":
            entered_a.set()
            release_a.wait(timeout=10)
        else:
            b_started.set()
        return noul_result(tag=state)

    model = make_fake(predict_fn=predict_fn)
    engine = InferenceEngine(model, concurrency=1, queue_size=4)
    engine.start()

    async def scenario() -> None:
        a = asyncio.create_task(engine.decide("A", NOUL, 60_000, "a"))
        assert await asyncio.to_thread(entered_a.wait, 5) is True
        b = asyncio.create_task(engine.decide("B", NOUL, 60_000, "b"))
        await asyncio.sleep(0.05)
        # A is still running: the single slot is NOT freed, so B cannot start.
        assert b_started.is_set() is False
        release_a.set()
        await a
        await b
        assert b_started.is_set() is True

    asyncio.run(scenario())
    engine.stop()


def test_late_result_not_written_into_newer_request() -> None:
    clock = ManualClock(1000.0)

    def predict_fn(state, questions):
        clock.advance(10.0)  # simulate slow CPU: always 10s of work
        value = 0.1 if state == "A" else 0.9
        return {
            "model": "rl-agent",
            "answers": {"q": {"type": "noul", "noul": value, "rl_agent": {}}},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }

    model = make_fake(predict_fn=predict_fn)
    engine = InferenceEngine(model, concurrency=1, queue_size=2, clock=clock)

    # A: deadline 5s but work takes 10s -> late, must be discarded.
    job_a = _Job(state="A", questions=NOUL, deadline=clock() + 5.0, request_id="a",
                 loop=None, enqueued_at=clock())
    engine._run_job(job_a)
    assert job_a.outcome.status == "DEADLINE_EXCEEDED"
    assert job_a.outcome.answers is None

    # B: fresh job with a far deadline -> OK, and its answer is B's own, not A's.
    job_b = _Job(state="B", questions=NOUL, deadline=clock() + 100.0, request_id="b",
                 loop=None, enqueued_at=clock())
    engine._run_job(job_b)
    assert job_b.outcome.status == "OK"
    assert job_b.outcome.answers is not None
    assert job_b.outcome.answers["q"]["noul"] == 0.9


def test_abandoned_job_is_discarded() -> None:
    clock = ManualClock(1000.0)
    model = make_fake(predict_fn=lambda s, q: noul_result())
    engine = InferenceEngine(model, concurrency=1, queue_size=2, clock=clock)
    job = _Job(state="A", questions=NOUL, deadline=clock() + 60.0, request_id="a",
               loop=None, enqueued_at=clock())
    job.abandoned = True  # the awaiting client already timed out
    engine._run_job(job)
    assert job.outcome.status == "DEADLINE_EXCEEDED"
    assert job.outcome.answers is None


def _blocking_predict(entered, release, block_on):
    def fn(state, questions):
        if state == block_on:
            entered.set()
            release.wait(timeout=10)
        return noul_result(tag=state)

    return fn
