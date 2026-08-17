import pytest

import app.api.dependencies.checkpointer as checkpointer_module
from app.api.dependencies.checkpointer import close_agent_checkpointer, get_agent_checkpointer


class _FakePool:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _FakeSaver:
    pass


@pytest.fixture(autouse=True)
async def _reset_module_state():
    # The module caches state in globals — reset before AND after each test
    # so tests don't leak into each other.
    await close_agent_checkpointer()
    yield
    await close_agent_checkpointer()


@pytest.mark.asyncio
async def test_get_agent_checkpointer_opens_the_pool_and_returns_a_saver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pool = _FakePool()
    fake_saver = _FakeSaver()
    monkeypatch.setattr(
        checkpointer_module, "create_postgres_checkpointer_pool", lambda conninfo: fake_pool
    )

    async def fake_create_checkpointer(pool):
        return fake_saver

    monkeypatch.setattr(checkpointer_module, "create_checkpointer", fake_create_checkpointer)

    saver = await get_agent_checkpointer()

    assert saver is fake_saver
    assert fake_pool.opened is True


@pytest.mark.asyncio
async def test_get_agent_checkpointer_caches_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = _FakePool()
    build_calls = 0

    def fake_pool_factory(conninfo):
        nonlocal build_calls
        build_calls += 1
        return fake_pool

    async def fake_create_checkpointer(pool):
        return _FakeSaver()

    monkeypatch.setattr(
        checkpointer_module, "create_postgres_checkpointer_pool", fake_pool_factory
    )
    monkeypatch.setattr(checkpointer_module, "create_checkpointer", fake_create_checkpointer)

    first = await get_agent_checkpointer()
    second = await get_agent_checkpointer()

    assert first is second
    assert build_calls == 1


@pytest.mark.asyncio
async def test_close_agent_checkpointer_closes_the_pool_and_clears_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pool = _FakePool()
    monkeypatch.setattr(
        checkpointer_module, "create_postgres_checkpointer_pool", lambda conninfo: fake_pool
    )

    async def fake_create_checkpointer(pool):
        return _FakeSaver()

    monkeypatch.setattr(checkpointer_module, "create_checkpointer", fake_create_checkpointer)
    await get_agent_checkpointer()

    await close_agent_checkpointer()

    assert fake_pool.closed is True


@pytest.mark.asyncio
async def test_close_agent_checkpointer_is_a_no_op_when_never_opened() -> None:
    # Must not raise even though no pool was ever created.
    await close_agent_checkpointer()
