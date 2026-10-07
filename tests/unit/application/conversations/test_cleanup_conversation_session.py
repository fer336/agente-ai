from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations.cleanup_conversation_session import (
    CleanupConversationSessionUseCase,
    CleanupOutcome,
)
from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.conversations.schedule_conversation_reset import (
    CONVERSATION_IDLE_RESET_ACTION,
    ScheduleConversationResetUseCase,
)
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.entities.contact_memory import ContactMemory
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.agent.fake_session_checkpoint_repository import (
    FakeSessionCheckpointRepository,
)
from app.infrastructure.database.fake_appointment_reminder_repository import (
    FakeAppointmentReminderRepository,
)
from app.infrastructure.database.fake_contact_memory_repository import (
    FakeContactMemoryRepository,
)
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.database.fake_pending_action_repository import FakePendingActionRepository
from app.infrastructure.database.fake_scheduled_action_repository import (
    FakeScheduledActionRepository,
)
from tests.fixtures.gateways import make_memory_service
from tests.fixtures.seed_objects import (
    make_contact,
    make_conversation,
    make_pending_action,
    make_scheduled_action,
)

CONVERSATION_ID = "conv-1"


@dataclass
class Harness:
    use_case: CleanupConversationSessionUseCase
    conversations: FakeConversationRepository
    contacts: FakeContactRepository
    pending_actions: FakePendingActionRepository
    scheduled_actions: FakeScheduledActionRepository
    contact_memories: FakeContactMemoryRepository
    checkpoints: FakeSessionCheckpointRepository


def _harness() -> Harness:
    conversations = FakeConversationRepository()
    contacts = FakeContactRepository()
    pending_actions = FakePendingActionRepository()
    scheduled_actions = FakeScheduledActionRepository()
    contact_memories = FakeContactMemoryRepository()
    checkpoints = FakeSessionCheckpointRepository(
        threads={
            "conv-1:session:1",
            "conv-1:session:2",
            "conv-1:session:3",
            "conv-10:session:1",
            "conv-2:session:1",
        }
    )

    @asynccontextmanager
    async def provider() -> AsyncIterator[RotateWorkflowSessionUseCase.Repositories]:
        yield RotateWorkflowSessionUseCase.Repositories(
            conversations=conversations,
            pending_actions=pending_actions,
            scheduled_actions=scheduled_actions,
        )

    use_case = CleanupConversationSessionUseCase(
        conversations=conversations,
        contacts=contacts,
        rotate_workflow_session=RotateWorkflowSessionUseCase(provider),
        session_checkpoints=checkpoints,
        memory_service=make_memory_service(contact_memory_repository=contact_memories),
    )
    return Harness(
        use_case,
        conversations,
        contacts,
        pending_actions,
        scheduled_actions,
        contact_memories,
        checkpoints,
    )


async def _seed(h: Harness, *, mode: str = "agent", generation: int = 3) -> None:
    conversation = make_conversation(id_=CONVERSATION_ID, contact_id="contact-1", mode=mode)
    conversation.workflow_session_generation = generation
    await h.conversations.save(conversation)
    await h.contacts.save(make_contact(id_="contact-1"))
    await h.contact_memories.save(
        ContactMemory(
            id="mem-1",
            contact_id="contact-1",
            summary="old summary",
            last_compacted_message_id=None,
            last_compacted_at=None,
            updated_at=conversation.created_at,
        )
    )


@pytest.mark.asyncio
async def test_cleans_session_checkpoints_memory_and_pending_actions():
    h = _harness()
    await _seed(h)
    # An action parked on an OLDER generation must be expired too.
    await h.pending_actions.save(
        make_pending_action(id_="pa-old", conversation_id=CONVERSATION_ID, workflow_generation=2)
    )
    await h.pending_actions.save(
        make_pending_action(id_="pa-cur", conversation_id=CONVERSATION_ID, workflow_generation=3)
    )
    await h.scheduled_actions.save(
        make_scheduled_action(
            id_="sa-1", conversation_id=CONVERSATION_ID, pending_action_id="pa-cur"
        )
    )

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.CLEANED
    stored = await h.conversations.get_by_id(ConversationId(CONVERSATION_ID))
    assert stored is not None
    assert stored.workflow_session_generation == 4
    assert h.checkpoints.threads == {"conv-10:session:1", "conv-2:session:1"}
    assert await h.contact_memories.get_by_contact_id("contact-1") is None
    for pending_id in ("pa-old", "pa-cur"):
        pending = await h.pending_actions.get_by_id(pending_id)
        assert pending is not None
        assert pending.status == "expired"
    scheduled = await h.scheduled_actions.get_by_id("sa-1")
    assert scheduled is not None
    assert scheduled.status == "cancelled"


@pytest.mark.asyncio
async def test_missing_conversation_is_skipped_without_side_effects():
    h = _harness()

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.SKIPPED_CONVERSATION_MISSING
    assert h.checkpoints.calls == []


@pytest.mark.asyncio
async def test_human_mode_conversation_is_skipped_and_keeps_its_context():
    h = _harness()
    await _seed(h, mode="human")

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.SKIPPED_NOT_AGENT_MODE
    stored = await h.conversations.get_by_id(ConversationId(CONVERSATION_ID))
    assert stored is not None
    assert stored.workflow_session_generation == 3
    assert h.checkpoints.calls == []
    assert await h.contact_memories.get_by_contact_id("contact-1") is not None


@pytest.mark.asyncio
async def test_missing_contact_is_skipped_without_rotating():
    h = _harness()
    await _seed(h)
    h.contacts = FakeContactRepository()
    h.use_case = CleanupConversationSessionUseCase(
        conversations=h.conversations,
        contacts=h.contacts,
        rotate_workflow_session=RotateWorkflowSessionUseCase(h.conversations),
        session_checkpoints=h.checkpoints,
        memory_service=make_memory_service(contact_memory_repository=h.contact_memories),
    )

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.SKIPPED_CONTACT_MISSING
    stored = await h.conversations.get_by_id(ConversationId(CONVERSATION_ID))
    assert stored is not None
    assert stored.workflow_session_generation == 3
    assert h.checkpoints.calls == []


@pytest.mark.asyncio
async def test_lost_rotation_race_does_nothing_destructive():
    h = _harness()
    await _seed(h)

    class _LosingRotation:
        async def execute(self, *args: object, **kwargs: object) -> bool:
            return False

    h.use_case = CleanupConversationSessionUseCase(
        conversations=h.conversations,
        contacts=h.contacts,
        rotate_workflow_session=_LosingRotation(),  # type: ignore[arg-type]
        session_checkpoints=h.checkpoints,
        memory_service=make_memory_service(contact_memory_repository=h.contact_memories),
    )

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.ROTATION_LOST
    assert h.checkpoints.calls == []
    assert await h.contact_memories.get_by_contact_id("contact-1") is not None


@pytest.mark.asyncio
async def test_second_run_is_a_data_noop():
    h = _harness()
    await _seed(h)

    first = await h.use_case.execute(ConversationId(CONVERSATION_ID))
    second = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert first is CleanupOutcome.CLEANED
    assert second is CleanupOutcome.CLEANED
    assert h.checkpoints.threads == {"conv-10:session:1", "conv-2:session:1"}
    assert await h.contact_memories.get_by_contact_id("contact-1") is None
    # The second run only retires generations that were already empty.
    assert h.checkpoints.calls[-1] == (CONVERSATION_ID, 4)


PHONE = "+5491122334455"
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
STARTS_AT = NOW + timedelta(hours=20)
IDLE_DELAY = 10_800


def _reminder(*, starts_at=STARTS_AT, status="sent", kind="confirm_day_before", phone=PHONE):
    return AppointmentReminder(
        "r-1",
        "apt-1",
        "patient-1",
        kind,
        status,
        NOW,
        phone,
        sent_at=NOW - timedelta(hours=1),
        appointment_starts_at=starts_at,
    )


def _with_reminders(h: Harness, *reminders: AppointmentReminder) -> None:
    h.use_case = CleanupConversationSessionUseCase(
        conversations=h.conversations,
        contacts=h.contacts,
        rotate_workflow_session=h.use_case._rotate_workflow_session,
        session_checkpoints=h.checkpoints,
        memory_service=make_memory_service(contact_memory_repository=h.contact_memories),
        appointment_reminders=FakeAppointmentReminderRepository(list(reminders)),
        schedule_conversation_reset=ScheduleConversationResetUseCase(
            h.scheduled_actions, IDLE_DELAY
        ),
        clock=lambda: NOW,
    )


async def _idle_actions(h: Harness) -> list:
    return [
        action
        for action in await h.scheduled_actions.get_scheduled_by_conversation_id(CONVERSATION_ID)
        if action.action_type == CONVERSATION_IDLE_RESET_ACTION
    ]


@pytest.mark.asyncio
async def test_cleanup_is_deferred_while_a_sent_reminder_has_a_future_appointment():
    h = _harness()
    await _seed(h)
    _with_reminders(h, _reminder())

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.SKIPPED_PENDING_REMINDER
    stored = await h.conversations.get_by_id(ConversationId(CONVERSATION_ID))
    assert stored is not None and stored.workflow_session_generation == 3
    assert h.checkpoints.calls == []
    assert await h.contact_memories.get_by_contact_id("contact-1") is not None


@pytest.mark.asyncio
async def test_a_deferred_cleanup_is_rescheduled_once_for_the_appointment_start_plus_the_delay():
    h = _harness()
    await _seed(h)
    _with_reminders(h, _reminder())

    await h.use_case.execute(ConversationId(CONVERSATION_ID))
    await h.use_case.execute(ConversationId(CONVERSATION_ID))

    [action] = await _idle_actions(h)
    assert action.scheduled_for == STARTS_AT + timedelta(seconds=IDLE_DELAY)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reminders",
    [
        [],
        [_reminder(starts_at=NOW - timedelta(minutes=1))],
        [_reminder(starts_at=None)],
        [_reminder(status="pending")],
        [_reminder(kind="review_request")],
        [_reminder(phone="+5491199999999")],
    ],
)
async def test_cleanup_runs_normally_without_a_pending_reminder(reminders):
    h = _harness()
    await _seed(h)
    _with_reminders(h, *reminders)

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.CLEANED
    assert await h.contact_memories.get_by_contact_id("contact-1") is None
    assert await _idle_actions(h) == []


@pytest.mark.asyncio
async def test_human_mode_is_still_skipped_and_nothing_is_rescheduled():
    h = _harness()
    await _seed(h, mode="human")
    _with_reminders(h, _reminder())

    outcome = await h.use_case.execute(ConversationId(CONVERSATION_ID))

    assert outcome is CleanupOutcome.SKIPPED_NOT_AGENT_MODE
    assert await _idle_actions(h) == []


@pytest.mark.asyncio
async def test_cleanup_without_reminder_wiring_behaves_as_before():
    h = _harness()
    await _seed(h)

    assert await h.use_case.execute(ConversationId(CONVERSATION_ID)) is CleanupOutcome.CLEANED
