"""Shared fake-gateway factory functions for tests.

Plain factory functions (not `@pytest.fixture`s) — fakes have no
setup/teardown lifecycle, so a callable constructor is sufficient and
matches the call shape of the inline `Fake*()` construction these replace.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.application.messages.ingest_message import IngestMessageUseCase, MessageRepositories
from app.application.messages.send_reply import SendReplyUseCase
from app.domain.entities.appointment_slot import AppointmentSlot
from app.infrastructure.agent.fake_agent_invoker import FakeAgentInvoker
from app.infrastructure.chatwoot.fake_chatwoot_conversation_gateway import (
    FakeChatwootConversationGateway,
)
from app.infrastructure.chatwoot.fake_chatwoot_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_message_repository import FakeMessageRepository
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.redis.debounce import DebounceTracker
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway
from tests.fixtures.fake_redis import InMemoryFakeRedis


def make_dentalink_gateway(
    available_slots: list[AppointmentSlot] | None = None,
) -> FakeDentalinkGateway:
    return FakeDentalinkGateway(available_slots=available_slots)


def make_chatwoot_gateway() -> FakeChatwootGateway:
    return FakeChatwootGateway()


def make_whatsapp_gateway() -> FakeWhatsAppGateway:
    return FakeWhatsAppGateway()


def make_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


def make_contact_repository() -> FakeContactRepository:
    return FakeContactRepository()


def make_message_repository() -> FakeMessageRepository:
    return FakeMessageRepository()


def make_conversation_repository() -> FakeConversationRepository:
    return FakeConversationRepository()


def make_agent_invoker() -> FakeAgentInvoker:
    return FakeAgentInvoker()


def make_chatwoot_conversation_gateway() -> FakeChatwootConversationGateway:
    return FakeChatwootConversationGateway()


def make_send_reply_use_case(
    messaging_gateway: FakeWhatsAppGateway | None = None,
    chatwoot_gateway: FakeChatwootConversationGateway | None = None,
) -> SendReplyUseCase:
    messaging_gateway = (
        messaging_gateway if messaging_gateway is not None else make_whatsapp_gateway()
    )
    chatwoot_gateway = (
        chatwoot_gateway if chatwoot_gateway is not None else make_chatwoot_conversation_gateway()
    )
    return SendReplyUseCase(messaging_gateway, chatwoot_gateway)


def make_ingest_message_use_case(
    message_repository: FakeMessageRepository | None = None,
    contact_repository: FakeContactRepository | None = None,
    conversation_repository: FakeConversationRepository | None = None,
    redis_client: InMemoryFakeRedis | None = None,
    agent_invoker: FakeAgentInvoker | None = None,
    debounce_seconds: int = 6,
) -> IngestMessageUseCase:
    """Builds an `IngestMessageUseCase` wired entirely to fakes.

    Used both by `tests/unit/application/messages/test_ingest_message.py`
    and by `tests/unit/api/routes/test_webhook.py` (via
    `app.dependency_overrides[get_ingest_message_use_case]`) so route-level
    tests never construct the real, Postgres/Redis-backed production
    singleton (`app.api.dependencies.use_cases.get_ingest_message_use_case`).
    """
    message_repository = (
        message_repository if message_repository is not None else make_message_repository()
    )
    contact_repository = (
        contact_repository if contact_repository is not None else make_contact_repository()
    )
    conversation_repository = (
        conversation_repository
        if conversation_repository is not None
        else make_conversation_repository()
    )
    redis_client = redis_client if redis_client is not None else InMemoryFakeRedis()
    agent_invoker = agent_invoker if agent_invoker is not None else make_agent_invoker()
    debounce_tracker = DebounceTracker(redis_client, debounce_seconds)

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[MessageRepositories]:
        yield MessageRepositories(
            messages=message_repository,
            contacts=contact_repository,
            conversations=conversation_repository,
        )

    return IngestMessageUseCase(
        repositories_provider=repositories_provider,
        debounce_tracker=debounce_tracker,
        redis_client=redis_client,
        agent_invoker=agent_invoker,
        debounce_seconds=debounce_seconds,
    )
