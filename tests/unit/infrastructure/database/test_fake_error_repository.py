from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.error_record import SOURCE_DENTALINK
from app.domain.repositories.error_repository import ErrorRepository
from app.infrastructure.database.fake_error_repository import FakeErrorRepository
from tests.fixtures.gateways import make_error_repository
from tests.fixtures.seed_objects import make_error_record


@pytest.mark.asyncio
async def test_save_then_get_by_id_round_trips():
    repository = make_error_repository()
    error = make_error_record(id_="err-1")

    await repository.save(error)
    fetched = await repository.get_by_id("err-1")

    assert fetched is error


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = make_error_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_count_recent_only_counts_matching_source_and_error_type_since():
    repository = make_error_repository()
    now = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    await repository.save(
        make_error_record(
            id_="err-1",
            source=SOURCE_DENTALINK,
            error_type="dentalink_timeout",
            created_at=now,
        )
    )
    await repository.save(
        make_error_record(
            id_="err-2",
            source=SOURCE_DENTALINK,
            error_type="dentalink_timeout",
            created_at=now - timedelta(minutes=5),
        )
    )
    await repository.save(
        make_error_record(
            id_="err-3",
            source=SOURCE_DENTALINK,
            error_type="dentalink_auth_error",
            created_at=now,
        )
    )

    count = await repository.count_recent(
        SOURCE_DENTALINK, "dentalink_timeout", since=now - timedelta(minutes=2)
    )

    assert count == 1


def test_fake_error_repository_satisfies_protocol():
    assert isinstance(FakeErrorRepository(), ErrorRepository)
