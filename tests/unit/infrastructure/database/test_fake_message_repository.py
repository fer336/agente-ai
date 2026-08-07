import pytest

from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from tests.fixtures.seed_objects import make_message


def test_fake_message_repository_satisfies_message_repository_protocol():
    assert isinstance(FakeMessageRepository(), MessageRepository)


@pytest.mark.asyncio
async def test_exists_by_external_id_is_false_before_save():
    repository = FakeMessageRepository()

    assert await repository.exists_by_external_id(ExternalMessageId("wamid.1")) is False


@pytest.mark.asyncio
async def test_exists_by_external_id_is_true_after_save():
    repository = FakeMessageRepository()
    message = make_message(external_message_id="wamid.1")

    await repository.save(message)

    assert await repository.exists_by_external_id(ExternalMessageId("wamid.1")) is True
