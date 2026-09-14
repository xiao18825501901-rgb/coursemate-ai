"""Bounded SSE framing, shared by Qwen transports. Never counts [DONE] as model success."""
from collections.abc import AsyncIterable, AsyncIterator

async def events(lines: AsyncIterable[str], max_event_chars: int = 1_000_000) -> AsyncIterator[tuple[str, str]]:
    event_type = 'message'
    data: list[str] = []
    count = 0
    first = True
    async for raw in lines:
        line = raw.lstrip('\ufeff') if first else raw
        first = False
        if line == '':
            if data:
                yield event_type, '\n'.join(data)
            event_type, data, count = 'message', [], 0
            continue
        if line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        if value.startswith(' '):
            value = value[1:]
        if field == 'data':
            count += len(value)
            if count > max_event_chars:
                raise ValueError('SSE_EVENT_TOO_LARGE')
            data.append(value)
        elif field == 'event':
            event_type = value
    # Do not dispatch a non-terminated last event. A complete model terminal event is required.
