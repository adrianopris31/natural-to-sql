"""Tests for SSE heartbeat interleaving (keeps proxies from dropping idle streams)."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.services.chat import SSE_HEARTBEAT, with_heartbeat


async def _slow_events() -> AsyncIterator[str]:
    yield 'event: status\ndata: "generating_sql"\n\n'
    await asyncio.sleep(0.35)
    yield "event: done\ndata: {}\n\n"


@pytest.mark.asyncio
async def test_heartbeat_emitted_while_idle_and_events_preserved() -> None:
    out = [chunk async for chunk in with_heartbeat(_slow_events(), interval_sec=0.1)]

    assert out[0].startswith("event: status")
    assert out[-1].startswith("event: done")
    assert out.count(SSE_HEARTBEAT) >= 2
    assert [c for c in out if c != SSE_HEARTBEAT] == [out[0], out[-1]]


@pytest.mark.asyncio
async def test_no_heartbeat_when_events_are_fast() -> None:
    async def fast() -> AsyncIterator[str]:
        for i in range(3):
            yield f"event: status\ndata: {i}\n\n"

    out = [chunk async for chunk in with_heartbeat(fast(), interval_sec=1.0)]
    assert SSE_HEARTBEAT not in out
    assert len(out) == 3


@pytest.mark.asyncio
async def test_exceptions_from_wrapped_generator_propagate() -> None:
    async def boom() -> AsyncIterator[str]:
        yield "event: status\ndata: 1\n\n"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _ = [chunk async for chunk in with_heartbeat(boom(), interval_sec=1.0)]


@pytest.mark.asyncio
async def test_closing_consumer_cancels_wrapped_generator() -> None:
    cancelled = asyncio.Event()

    async def forever() -> AsyncIterator[str]:
        try:
            yield "event: status\ndata: 1\n\n"
            await asyncio.sleep(10)
            yield "never"
        except asyncio.CancelledError:
            cancelled.set()
            raise

    gen = with_heartbeat(forever(), interval_sec=0.05)
    assert (await anext(gen)).startswith("event: status")
    await gen.aclose()
    await asyncio.wait_for(cancelled.wait(), timeout=1)
