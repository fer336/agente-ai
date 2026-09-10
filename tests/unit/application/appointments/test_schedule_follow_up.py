from datetime import UTC, datetime, timedelta

import pytest

from app.application.appointments.schedule_follow_up import (
    APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
    ScheduleFollowUpUseCase,
)
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.gateways import make_scheduled_action_repository
from tests.fixtures.seed_objects import make_scheduled_action


@pytest.mark.asyncio
async def test_reconcile_schedules_a_prompt_when_the_tramite_is_still_open():
    repository = make_scheduled_action_repository()
    use_case = ScheduleFollowUpUseCase(repository, prompt_delay_seconds=1200)

    await use_case.reconcile(ConversationId("conv-1"), "awaiting_identification")

    scheduled = await repository.get_scheduled_by_conversation_id("conv-1")
    assert len(scheduled) == 1
    assert scheduled[0].action_type == APPOINTMENT_FLOW_FOLLOW_UP_PROMPT
    assert scheduled[0].pending_action_id is None


@pytest.mark.asyncio
async def test_reconcile_schedules_roughly_prompt_delay_seconds_from_now():
    repository = make_scheduled_action_repository()
    use_case = ScheduleFollowUpUseCase(repository, prompt_delay_seconds=1200)

    before = datetime.now(UTC)
    await use_case.reconcile(ConversationId("conv-1"), "awaiting_identification")
    after = datetime.now(UTC)

    scheduled = await repository.get_scheduled_by_conversation_id("conv-1")
    assert before + timedelta(seconds=1200) <= scheduled[0].scheduled_for
    assert scheduled[0].scheduled_for <= after + timedelta(seconds=1200)


@pytest.mark.asyncio
async def test_reconcile_cancels_any_pending_follow_up_when_the_tramite_ended():
    repository = make_scheduled_action_repository()
    await repository.save(
        make_scheduled_action(
            id_="sa-stale",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
            status="scheduled",
        )
    )
    use_case = ScheduleFollowUpUseCase(repository, prompt_delay_seconds=1200)

    await use_case.reconcile(ConversationId("conv-1"), None)

    stale = await repository.get_by_id("sa-stale")
    assert stale is not None
    assert stale.status == "cancelled"
    assert await repository.get_scheduled_by_conversation_id("conv-1") == []


@pytest.mark.asyncio
async def test_reconcile_replaces_a_stale_follow_up_with_a_fresh_one():
    # The 20-minute window always counts from the agent's MOST RECENT
    # reply — a patient who keeps the trámite alive across several turns
    # must not have their follow-up fire based on a much earlier turn.
    repository = make_scheduled_action_repository()
    await repository.save(
        make_scheduled_action(
            id_="sa-old",
            conversation_id="conv-1",
            pending_action_id=None,
            action_type=APPOINTMENT_FLOW_FOLLOW_UP_PROMPT,
            status="scheduled",
            scheduled_for=datetime.now(UTC) - timedelta(minutes=15),
        )
    )
    use_case = ScheduleFollowUpUseCase(repository, prompt_delay_seconds=1200)

    await use_case.reconcile(ConversationId("conv-1"), "awaiting_identification")

    old = await repository.get_by_id("sa-old")
    assert old is not None
    assert old.status == "cancelled"
    scheduled = await repository.get_scheduled_by_conversation_id("conv-1")
    assert len(scheduled) == 1
    assert scheduled[0].id != "sa-old"


@pytest.mark.asyncio
async def test_reconcile_never_touches_an_unrelated_scheduled_action_type():
    # `appointment_confirmation_timeout` rows belong to a different
    # mechanism (`ProposeAppointmentUseCase`) and must survive untouched —
    # both can be scheduled for the same conversation at once.
    repository = make_scheduled_action_repository()
    await repository.save(
        make_scheduled_action(
            id_="sa-confirmation",
            conversation_id="conv-1",
            pending_action_id="pa-1",
            action_type="appointment_confirmation_timeout",
            status="scheduled",
        )
    )
    use_case = ScheduleFollowUpUseCase(repository, prompt_delay_seconds=1200)

    await use_case.reconcile(ConversationId("conv-1"), None)

    confirmation = await repository.get_by_id("sa-confirmation")
    assert confirmation is not None
    assert confirmation.status == "scheduled"
