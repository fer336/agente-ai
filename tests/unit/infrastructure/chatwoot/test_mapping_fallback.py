import logging

import pytest

from app.domain.entities.chatwoot_conversation_mapping import ChatwootConversationMapping
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.chatwoot.mapping_fallback import ChatwootContactMappingFallback
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)

_STORED = ChatwootConversationMapping(
    conversation_id="ycloud-+5491122334455",
    chatwoot_contact_id="1",
    chatwoot_conversation_id="99",
)


class _RaisingGateway(FakeChatwootGateway):
    async def find_conversation_contact(self, chatwoot_conversation_id: str):
        raise RuntimeError("chatwoot down")


@pytest.mark.asyncio
async def test_stored_mapping_wins_over_the_gateway_lookup():
    repository = FakeChatwootMappingRepository()
    await repository.save(_STORED)
    gateway = FakeChatwootGateway()
    gateway.contacts_by_conversation["99"] = ("8", "+5491100000000")
    decorated = ChatwootContactMappingFallback(repository, gateway)

    assert await decorated.get_by_chatwoot_conversation_id("99") == _STORED


@pytest.mark.asyncio
async def test_missing_mapping_falls_back_to_a_transient_one_built_from_the_contact():
    repository = FakeChatwootMappingRepository()
    gateway = FakeChatwootGateway()
    gateway.contacts_by_conversation["43"] = ("8", "+5491199887766")
    decorated = ChatwootContactMappingFallback(repository, gateway)

    mapping = await decorated.get_by_chatwoot_conversation_id("43")

    assert mapping == ChatwootConversationMapping(
        conversation_id="ycloud-+5491199887766",
        chatwoot_contact_id="8",
        chatwoot_conversation_id="43",
    )
    assert await repository.get_by_conversation_id("ycloud-+5491199887766") is None


@pytest.mark.asyncio
async def test_returns_none_when_the_gateway_knows_no_contact():
    decorated = ChatwootContactMappingFallback(
        FakeChatwootMappingRepository(), FakeChatwootGateway()
    )

    assert await decorated.get_by_chatwoot_conversation_id("43") is None


@pytest.mark.asyncio
async def test_gateway_failure_returns_none_and_logs_a_warning(caplog):
    decorated = ChatwootContactMappingFallback(FakeChatwootMappingRepository(), _RaisingGateway())

    with caplog.at_level(logging.WARNING):
        result = await decorated.get_by_chatwoot_conversation_id("43")

    assert result is None
    assert any("mapping_fallback" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_other_operations_delegate_to_the_wrapped_repository():
    repository = FakeChatwootMappingRepository()
    decorated = ChatwootContactMappingFallback(repository, FakeChatwootGateway())

    await decorated.save(_STORED)

    assert await decorated.get_by_conversation_id(_STORED.conversation_id) == _STORED
    assert await repository.get_by_conversation_id(_STORED.conversation_id) == _STORED
