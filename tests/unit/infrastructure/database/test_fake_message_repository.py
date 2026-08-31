from datetime import UTC, datetime

import pytest

from app.domain.repositories.message_repository import MessageRepository
from app.domain.value_objects.conversation_id import ConversationId
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


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing():
    repository = FakeMessageRepository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_get_by_id_returns_the_saved_message():
    repository = FakeMessageRepository()
    message = make_message(id_="msg-1")
    await repository.save(message)

    assert await repository.get_by_id("msg-1") == message


@pytest.mark.asyncio
async def test_update_persists_changes_to_an_existing_message():
    repository = FakeMessageRepository()
    message = make_message(id_="msg-1", text="")
    await repository.save(message)

    updated = make_message(id_="msg-1", text="transcripted text")
    await repository.update(updated)

    assert (await repository.get_by_id("msg-1")).text == "transcripted text"


@pytest.mark.asyncio
async def test_update_raises_when_message_does_not_exist():
    repository = FakeMessageRepository()

    with pytest.raises(ValueError):
        await repository.update(make_message(id_="missing"))


@pytest.mark.asyncio
async def test_get_by_conversation_id_returns_only_matching_messages_oldest_first():
    repository = FakeMessageRepository()

    await repository.save(
        make_message(
            id_="msg-2", conversation_id="conv-1", created_at=datetime(2026, 1, 1, 9, 5, tzinfo=UTC)
        )
    )
    await repository.save(
        make_message(
            id_="msg-1", conversation_id="conv-1", created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        )
    )
    await repository.save(
        make_message(
            id_="msg-other",
            conversation_id="conv-2",
            created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        )
    )

    fetched = await repository.get_by_conversation_id(ConversationId("conv-1"))

    assert [m.id for m in fetched] == ["msg-1", "msg-2"]
