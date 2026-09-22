from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.application.messages.mirror_to_chatwoot import MirrorMessageToChatwootUseCase
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)

_CONVERSATION_ID = ConversationId("ycloud-+5491122334455")
_PHONE = PhoneNumber("+5491122334455")


def _make_use_case(
    chatwoot_gateway: FakeChatwootGateway | None = None,
    mapping_repository: FakeChatwootMappingRepository | None = None,
) -> tuple[MirrorMessageToChatwootUseCase, FakeChatwootGateway, FakeChatwootMappingRepository]:
    chatwoot_gateway = chatwoot_gateway or FakeChatwootGateway()
    mapping_repository = mapping_repository or FakeChatwootMappingRepository()

    @asynccontextmanager
    async def provider() -> AsyncIterator[ChatwootMappingRepository]:
        yield mapping_repository

    return (
        MirrorMessageToChatwootUseCase(chatwoot_gateway, provider),
        chatwoot_gateway,
        mapping_repository,
    )


@pytest.mark.asyncio
async def test_mirror_incoming_creates_the_contact_and_conversation_on_first_call():
    use_case, gateway, mapping_repository = _make_use_case()

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola, quiero un turno")

    mapping = await mapping_repository.get_by_conversation_id(str(_CONVERSATION_ID))
    assert mapping is not None
    assert gateway.sent_incoming == [(mapping.chatwoot_conversation_id, "Hola, quiero un turno")]


@pytest.mark.asyncio
async def test_mirror_outgoing_creates_the_contact_and_conversation_on_first_call():
    use_case, gateway, mapping_repository = _make_use_case()

    await use_case.mirror_outgoing(_CONVERSATION_ID, _PHONE, str(_PHONE), "Tu turno fue confirmado")

    mapping = await mapping_repository.get_by_conversation_id(str(_CONVERSATION_ID))
    assert mapping is not None
    assert gateway.sent_outgoing == [(mapping.chatwoot_conversation_id, "Tu turno fue confirmado")]


@pytest.mark.asyncio
async def test_second_message_on_the_same_conversation_reuses_the_mapping_not_a_new_one():
    # Chatwoot has no idempotent "find or create conversation" endpoint —
    # a second contact/conversation creation would silently fork the
    # patient's Chatwoot thread in two.
    use_case, gateway, mapping_repository = _make_use_case()

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")
    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "quiero un turno")

    assert len(gateway.sent_incoming) == 2
    chatwoot_conversation_ids = {cid for cid, _ in gateway.sent_incoming}
    assert len(chatwoot_conversation_ids) == 1


@pytest.mark.asyncio
async def test_incoming_then_outgoing_on_the_same_conversation_share_one_mapping():
    use_case, gateway, _ = _make_use_case()

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")
    await use_case.mirror_outgoing(
        _CONVERSATION_ID, _PHONE, str(_PHONE), "¡Hola! ¿En qué te ayudo?"
    )

    assert len(gateway.sent_incoming) == 1
    assert len(gateway.sent_outgoing) == 1
    assert gateway.sent_incoming[0][0] == gateway.sent_outgoing[0][0]


@pytest.mark.asyncio
async def test_two_different_conversations_get_two_distinct_mappings():
    use_case, gateway, _ = _make_use_case()
    other_conversation_id = ConversationId("ycloud-+5491199887766")
    other_phone = PhoneNumber("+5491199887766")

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")
    await use_case.mirror_incoming(
        other_conversation_id, other_phone, str(other_phone), "Hola desde otro numero"
    )

    chatwoot_conversation_ids = {cid for cid, _ in gateway.sent_incoming}
    assert len(chatwoot_conversation_ids) == 2


@pytest.mark.asyncio
async def test_mirror_incoming_never_raises_when_the_gateway_fails():
    # Regla de oro: a Chatwoot outage must never propagate past this
    # use case — it is only ever a best-effort mirror.
    use_case, _, _ = _make_use_case(chatwoot_gateway=FakeChatwootGateway(fail=True))

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")


@pytest.mark.asyncio
async def test_mirror_outgoing_never_raises_when_the_gateway_fails():
    use_case, _, _ = _make_use_case(chatwoot_gateway=FakeChatwootGateway(fail=True))

    await use_case.mirror_outgoing(_CONVERSATION_ID, _PHONE, str(_PHONE), "Turno confirmado")


@pytest.mark.asyncio
async def test_mirror_incoming_never_raises_when_the_mapping_repository_fails():
    class _FailingMappingRepository:
        async def get_by_conversation_id(self, conversation_id: str):
            raise RuntimeError("db unreachable")

        async def save(self, mapping):
            raise RuntimeError("db unreachable")

    use_case, _, _ = _make_use_case(mapping_repository=_FailingMappingRepository())  # type: ignore[arg-type]

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")


@pytest.mark.asyncio
async def test_a_failed_first_attempt_does_not_persist_a_partial_mapping():
    # If contact/conversation creation fails mid-way, no mapping row should
    # be left behind — otherwise a later successful call could incorrectly
    # believe a Chatwoot conversation already exists.
    use_case, _, mapping_repository = _make_use_case(
        chatwoot_gateway=FakeChatwootGateway(fail=True)
    )

    await use_case.mirror_incoming(_CONVERSATION_ID, _PHONE, str(_PHONE), "Hola")

    assert await mapping_repository.get_by_conversation_id(str(_CONVERSATION_ID)) is None
