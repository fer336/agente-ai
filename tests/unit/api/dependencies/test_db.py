import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.db import get_db_session


@pytest.mark.asyncio
async def test_get_db_session_yields_an_async_session():
    generator = get_db_session()

    session = await generator.__anext__()
    try:
        assert isinstance(session, AsyncSession)
    finally:
        await session.close()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


@pytest.mark.asyncio
async def test_get_db_session_yields_a_new_session_bound_to_the_same_engine_each_call():
    first_generator = get_db_session()
    second_generator = get_db_session()

    first_session = await first_generator.__anext__()
    second_session = await second_generator.__anext__()
    try:
        assert first_session is not second_session
        assert first_session.bind is second_session.bind
    finally:
        await first_session.close()
        await second_session.close()
        with pytest.raises(StopAsyncIteration):
            await first_generator.__anext__()
        with pytest.raises(StopAsyncIteration):
            await second_generator.__anext__()
