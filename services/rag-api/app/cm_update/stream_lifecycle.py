"""Keep cancellation and worker leases alive while an upstream stream is silent."""
import asyncio
from contextlib import suppress


async def monitored_stream(stream, *, is_terminal, heartbeat, interval=1.0):
    iterator=stream.__aiter__()
    pending=None
    try:
        while True:
            if is_terminal(): raise asyncio.CancelledError()
            pending=asyncio.create_task(anext(iterator))
            while True:
                done,_=await asyncio.wait({pending},timeout=interval)
                if is_terminal(): raise asyncio.CancelledError()
                heartbeat()
                if done: break
            try:
                item=pending.result()
            except StopAsyncIteration:
                return
            pending=None
            yield item
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending,return_exceptions=True)
        close=getattr(iterator,'aclose',None)
        if close:
            with suppress(asyncio.CancelledError):
                await close()
