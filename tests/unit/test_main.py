import asyncio

import pytest

from app import main as main_module


@pytest.mark.asyncio
async def test_lifespan_starts_the_follow_up_loop_and_cancels_it_cleanly(monkeypatch):
    call_count = 0

    async def fake_tick_once() -> None:
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(main_module, "_run_follow_up_tick_once", fake_tick_once)
    monkeypatch.setattr(main_module.asyncio, "sleep", lambda _seconds: asyncio.sleep(0))

    async with main_module.lifespan(main_module.app):
        # Let the loop actually run a few iterations of the real event loop.
        for _ in range(5):
            await asyncio.sleep(0)

    assert call_count >= 1


@pytest.mark.asyncio
async def test_a_tick_that_raises_never_kills_the_loop(monkeypatch):
    call_count = 0

    async def flaky_tick_once() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "_run_follow_up_tick_once", flaky_tick_once)
    monkeypatch.setattr(main_module.asyncio, "sleep", lambda _seconds: asyncio.sleep(0))

    async with main_module.lifespan(main_module.app):
        for _ in range(5):
            await asyncio.sleep(0)

    # Survived the first tick's exception and kept looping past it.
    assert call_count >= 2
