from datetime import UTC, datetime

import pytest

from app.application.admin.error_queries import ErrorQueryService
from tests.fixtures.gateways import make_error_repository
from tests.fixtures.seed_objects import make_error_record


@pytest.mark.asyncio
async def test_list_errors_returns_recent_errors():
    errors = make_error_repository()
    await errors.save(make_error_record(id_="err-1"))
    service = ErrorQueryService(errors)

    fetched = await service.list_errors()

    assert [e.id for e in fetched] == ["err-1"]


@pytest.mark.asyncio
async def test_get_error_detail_returns_none_when_missing():
    service = ErrorQueryService(make_error_repository())

    assert await service.get_error_detail("missing") is None


@pytest.mark.asyncio
async def test_resolve_sets_resolved_at_and_persists():
    errors = make_error_repository()
    await errors.save(make_error_record(id_="err-1", resolved_at=None))
    service = ErrorQueryService(errors)
    now = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)

    resolved = await service.resolve("err-1", now=now)

    assert resolved is not None
    assert resolved.resolved_at == now
    fetched = await errors.get_by_id("err-1")
    assert fetched.resolved_at == now


@pytest.mark.asyncio
async def test_resolve_returns_none_when_error_does_not_exist():
    service = ErrorQueryService(make_error_repository())

    assert await service.resolve("missing", now=datetime.now(UTC)) is None
