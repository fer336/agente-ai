from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from app.application.appointments.propose_appointment import (
    APPOINTMENT_CONFIRMATION_TIMEOUT,
    ProposalRepositories,
    ProposeAppointmentUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import (
    make_outbox_repository,
    make_pending_action_repository,
    make_scheduled_action_repository,
)


def _build_use_case(
    pending_action_repository=None,
    scheduled_action_repository=None,
    outbox_repository=None,
    confirmation_timeout_seconds: int = 120,
):
    pending_action_repository = pending_action_repository or make_pending_action_repository()
    scheduled_action_repository = scheduled_action_repository or make_scheduled_action_repository()
    outbox_repository = outbox_repository or make_outbox_repository()

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[ProposalRepositories]:
        yield ProposalRepositories(
            pending_actions=pending_action_repository,
            scheduled_actions=scheduled_action_repository,
            outbox=outbox_repository,
        )

    use_case = ProposeAppointmentUseCase(
        repositories_provider=repositories_provider,
        confirmation_timeout_seconds=confirmation_timeout_seconds,
    )
    return use_case, pending_action_repository, scheduled_action_repository, outbox_repository


@pytest.mark.asyncio
async def test_execute_creates_a_pending_action_with_the_given_action_type_and_payload():
    use_case, pending_action_repository, _, _ = _build_use_case()

    result = await use_case.execute(
        ConversationId("conv-1"), "create_appointment", {"slot_id": "slot-1"}
    )

    assert result.action_type == "create_appointment"
    assert result.payload == {"slot_id": "slot-1"}
    assert result.status == "pending"
    fetched = await pending_action_repository.get_by_id(result.id)
    assert fetched is not None
    assert fetched == result


@pytest.mark.asyncio
async def test_execute_sets_expires_at_the_configured_timeout_seconds_from_now():
    use_case, _, _, _ = _build_use_case(confirmation_timeout_seconds=120)
    before = datetime.now(UTC)

    result = await use_case.execute(ConversationId("conv-1"), "create_appointment", {})

    delta = (result.expires_at - before).total_seconds()
    assert 118 <= delta <= 122


@pytest.mark.asyncio
async def test_execute_creates_a_matching_scheduled_action():
    use_case, _, scheduled_action_repository, _ = _build_use_case()

    pending_action = await use_case.execute(ConversationId("conv-1"), "create_appointment", {})

    due = await scheduled_action_repository.get_due(
        pending_action.expires_at, limit=10
    )
    matching = [sa for sa in due if sa.pending_action_id == pending_action.id]
    assert len(matching) == 1
    scheduled_action = matching[0]
    assert scheduled_action.action_type == APPOINTMENT_CONFIRMATION_TIMEOUT
    assert scheduled_action.status == "scheduled"
    assert scheduled_action.scheduled_for == pending_action.expires_at
    assert scheduled_action.conversation_id == ConversationId("conv-1")


@pytest.mark.asyncio
async def test_execute_creates_an_initial_outbox_event():
    use_case, _, _, outbox_repository = _build_use_case()

    pending_action = await use_case.execute(ConversationId("conv-1"), "create_appointment", {})

    pending_events = await outbox_repository.fetch_pending(limit=10)
    matching = [e for e in pending_events if e.aggregate_id == pending_action.id]
    assert len(matching) == 1
    event = matching[0]
    assert event.event_type == "appointment.proposed"
    assert event.aggregate_type == "pending_action"
    assert event.status == "pending"


@pytest.mark.asyncio
async def test_execute_writes_all_three_records_atomically_via_the_same_provider_call():
    # Not a real transaction-rollback test (fakes have no transactions) —
    # asserts the use case calls all three repositories exactly once each
    # within a single `repositories_provider()` unit of work, matching the
    # "one transaction" contract the real SQLAlchemy provider enforces via
    # an explicit commit.
    calls: list[str] = []

    class _TrackingPendingActionRepository:
        def __init__(self, inner):
            self._inner = inner

        async def save(self, pending_action):
            calls.append("pending_action")
            await self._inner.save(pending_action)

        async def get_by_id(self, pending_action_id):
            return await self._inner.get_by_id(pending_action_id)

        async def get_pending_for_conversation(self, conversation_id):
            return await self._inner.get_pending_for_conversation(conversation_id)

        async def mark_expired_if_pending(self, pending_action_id):
            return await self._inner.mark_expired_if_pending(pending_action_id)

    class _TrackingScheduledActionRepository:
        def __init__(self, inner):
            self._inner = inner

        async def save(self, scheduled_action):
            calls.append("scheduled_action")
            await self._inner.save(scheduled_action)

        async def get_by_id(self, scheduled_action_id):
            return await self._inner.get_by_id(scheduled_action_id)

        async def get_due(self, now, limit):
            return await self._inner.get_due(now, limit)

        async def transition_status(self, scheduled_action_id, *, from_status, to_status):
            return await self._inner.transition_status(
                scheduled_action_id, from_status=from_status, to_status=to_status
            )

    class _TrackingOutboxRepository:
        def __init__(self, inner):
            self._inner = inner

        async def save(self, event):
            calls.append("outbox")
            await self._inner.save(event)

        async def fetch_pending(self, limit):
            return await self._inner.fetch_pending(limit)

        async def mark_processed(self, event_id):
            await self._inner.mark_processed(event_id)

    use_case, _, _, _ = _build_use_case(
        pending_action_repository=_TrackingPendingActionRepository(make_pending_action_repository()),
        scheduled_action_repository=_TrackingScheduledActionRepository(
            make_scheduled_action_repository()
        ),
        outbox_repository=_TrackingOutboxRepository(make_outbox_repository()),
    )

    await use_case.execute(ConversationId("conv-1"), "create_appointment", {})

    assert calls == ["pending_action", "scheduled_action", "outbox"]
