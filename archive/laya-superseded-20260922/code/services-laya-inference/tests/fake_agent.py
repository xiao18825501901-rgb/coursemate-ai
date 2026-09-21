"""Test doubles for the Laya inference service (no torch, no network).

Provides a manual clock (for deterministic deadline tests) and factories that
produce :class:`app.model.FakeModel` instances with controllable ``predict``
behaviour (including blocking, to exercise the single-slot concurrency rules).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from app.model import FakeModel, ModelInfo


class ManualClock:
    """A monotonic-ish clock the test advances by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def noul_result(probability: float = 0.5, tag: str = "") -> dict[str, Any]:
    """An RLAgent-shaped result with a single noul answer (distinct by ``tag``)."""
    return {
        "model": "rl-agent",
        "answers": {
            "q": {
                "type": "noul",
                "noul": probability,
                "rl_agent": {"act_probability": 0.5},
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 0, "tag": tag},
    }


def make_fake(
    predict_fn: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    token_fn: Callable[[Any, dict[str, Any]], Any] | None = None,
    load_fn: Callable[[], None] | None = None,
    info: ModelInfo | None = None,
) -> FakeModel:
    return FakeModel(predict_fn=predict_fn, token_fn=token_fn, load_fn=load_fn, info=info)


def blocking_predict(
    entered: threading.Event,
    release: threading.Event,
    *,
    block_marker: str = "__BLOCK__",
    result: dict[str, Any] | None = None,
) -> Callable[[Any, dict[str, Any]], dict[str, Any]]:
    """A predict that blocks only when the state equals ``block_marker``."""

    def fn(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        if state == block_marker:
            entered.set()
            release.wait(timeout=10)
        return result if result is not None else noul_result()

    return fn


def advancing_predict(clock: ManualClock, seconds: float = 10.0) -> Callable[[Any, dict], dict]:
    """A predict that advances the injected clock (simulating slow CPU)."""

    def fn(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        clock.advance(seconds)
        return noul_result()

    return fn
