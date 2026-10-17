"""Read SDK SSE without retaining native reasoning or exposing partial answers."""

from collections.abc import Callable, Iterator
from typing import Any

import httpx
from openai import Stream
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.completion_usage import CompletionUsage


class NativeStreamFailure(Exception):
    """Only safe identity/usage survive an interrupted private stream."""

    def __init__(self, cause: Exception, metadata: dict[str, Any]) -> None:
        super().__init__(type(cause).__name__)
        self.cause, self.metadata = cause, metadata


class DeadlineResponseStream(httpx.SyncByteStream):
    """Public HTTP byte boundary, including SSE events skipped by the SDK."""

    def __init__(self, underlying: httpx.SyncByteStream, deadline: Callable[[], None]) -> None:
        self.underlying, self.deadline = underlying, deadline
        self.closed = False
        self.read_failure: Exception | None = None

    def __iter__(self) -> Iterator[bytes]:
        try:
            iterator = iter(self.underlying)
            while True:
                self.deadline()
                try:
                    block = next(iterator)
                except StopIteration:
                    self.deadline()
                    return
                self.deadline()
                yield block
        except Exception as error:
            self.read_failure = error
            raise

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.underlying.close()
            except Exception:
                if self.read_failure is not None:
                    raise self.read_failure from None
                raise


def collect_public_chat_stream(
    stream: Stream[ChatCompletionChunk],
    *,
    checkpoint: Callable[[], None] | None = None,
    wire_deadline: Callable[[], None] | None = None,
) -> tuple[ChatCompletion, bool]:
    """Require a stopped public answer and valid usage; discard native reasoning."""
    response_id, model = "", ""
    parts: list[str] = []
    usage: CompletionUsage | None = None
    observed = False
    stopped = False
    invalid = False
    identity_changed = False
    initialized = False
    failure: Exception | None = None
    try:
        if wire_deadline is not None:
            underlying = stream.response.stream
            if not isinstance(underlying, httpx.SyncByteStream):
                raise TypeError("The bounded synchronous stream requires a byte-stream boundary.")
            stream.response.stream = DeadlineResponseStream(underlying, wire_deadline)
        for chunk in stream:
            if checkpoint is not None:
                checkpoint()
            if not initialized:
                response_id, model = chunk.id, chunk.model
                initialized = True
            elif chunk.id != response_id or chunk.model != model:
                identity_changed = True
            if not chunk.id or not chunk.model:
                identity_changed = True
            if chunk.usage is not None:
                incoming = chunk.usage
                counts = (incoming.prompt_tokens, incoming.completion_tokens)
                valid = (
                    all(type(value) is int and value >= 0 for value in counts)
                    and sum(counts) > 0
                    and type(incoming.total_tokens) is int
                    and incoming.total_tokens == sum(counts)
                )
                if valid and (usage is None or usage == incoming):
                    usage = incoming
                else:
                    invalid = True
            if not chunk.choices:
                continue
            if len(chunk.choices) != 1 or chunk.choices[0].index != 0:
                invalid = True
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            native = getattr(delta, "reasoning_content", None)
            if native is not None:
                if not isinstance(native, str):
                    invalid = True
                elif native:
                    observed = True
            if delta.tool_calls or delta.function_call or delta.refusal:
                invalid = True
            if delta.content:
                if stopped or not isinstance(delta.content, str):
                    invalid = True
                else:
                    parts.append(delta.content)
            if choice.finish_reason is not None:
                if stopped or choice.finish_reason != "stop":
                    invalid = True
                stopped = True
        if checkpoint is not None:
            checkpoint()
    except Exception as error:
        failure = error
    finally:
        try:
            stream.close()
        except Exception as close_error:
            if failure is None:
                failure = close_error
    if failure is not None:
        raise NativeStreamFailure(
            failure,
            {
                "provider_response_id": response_id or None,
                "returned_model": "UNVERIFIED_STREAM_IDENTITY" if identity_changed else model,
                "usage_reported": usage is not None,
                "input_tokens": usage.prompt_tokens if usage is not None else None,
                "output_tokens": usage.completion_tokens if usage is not None else None,
                "native_reasoning_observed": observed,
            },
        ) from failure
    response = ChatCompletion(
        id=response_id,
        object="chat.completion",
        created=0,
        model="UNVERIFIED_STREAM_IDENTITY" if identity_changed else model,
        usage=usage,
        choices=[
            {
                "index": 0,
                "finish_reason": "stop" if stopped and not invalid else "length",
                "message": {"role": "assistant", "content": "".join(parts)},
            }
        ],
    )
    return response, observed
