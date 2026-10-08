"""Graph-level: REMINDER_RESCHEDULE tap -> slots -> pick -> the same appointment is rescheduled."""

from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import compile_graph
from app.agent.nodes.appointment import (
    CONFIRM_APPOINTMENT_PAYLOAD,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_SLOT_SELECTION,
)
from app.application.reminders.actions import HandleReminderActionUseCase
from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.repositories.gateways import ReminderAppointment, ReminderPatient
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.fake_appointment_gateway import FakeReminderAppointmentGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import future_slot
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agreement_gateway,
    make_conversation_repository,
    make_dentalink_gateway,
    make_error_service,
    make_node_execution_repository,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
    make_tool_execution_repository,
    make_ycloud_handoff_gateway,
)
from tests.fixtures.seed_objects import (
    make_contact,
    make_conversation,
    make_patient,
    make_professional,
    make_specialty,
)

PHONE = PhoneNumber("+5491122334455")
STALE = "Este recordatorio ya no está disponible."


class _Reminders:
    def __init__(self, reminder):
        self.reminder = reminder

    async def find_sent_for_inbound_action(self, appointment_id, recipient_phone, allowed_kinds):
        if self.reminder.appointment_id == appointment_id and self.reminder.kind in allowed_kinds:
            return self.reminder
        return None


class _Patients:
    async def get_reminder_patient(self, patient_id):
        return ReminderPatient(patient_id, PHONE, "Ada")


class _Contacts:
    async def get_by_id(self, contact_id):
        return make_contact(id_=contact_id, phone=str(PHONE))


async def _build(*, reminder_state="active"):
    appointment_gateway = make_dentalink_gateway(
        available_slots=[future_slot("slot-new", days=3)],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"),
        slot=future_slot("slot-old", days=1),
        idempotency_key="seed",
    )
    now = datetime.now(UTC)
    reminder = AppointmentReminder(
        "r-1",
        str(appointment.id),
        "pat-1",
        "confirm_or_location_same_day",
        "sent",
        now,
        str(PHONE),
    )
    reminder_gateway = FakeReminderAppointmentGateway(
        [
            ReminderAppointment(
                str(appointment.id), "pat-1", now, "1", reminder_state, reminder_state
            )
        ]
    )
    conversations = make_conversation_repository()
    await conversations.save(make_conversation(id_="conv-1", mode="agent"))
    graph = compile_graph(
        appointment_gateway=appointment_gateway,
        agreement_gateway=make_agreement_gateway(),
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
        handoff_gateway=make_ycloud_handoff_gateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversations,
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
        checkpointer=MemorySaver(),
        reminder_action_use_case=HandleReminderActionUseCase(
            _Reminders(reminder), reminder_gateway, _Patients(), _Contacts(), now=lambda: now
        ),
        contact_repository=_Contacts(),
    )
    return graph, appointment_gateway, str(appointment.id)


async def _tap(graph, payload, previous=None):
    """One turn shaped like `LangGraphAgentInvoker`: carry collected_data/pending id over."""
    config = {"configurable": {"thread_id": "conv-1:session:1"}}
    previous = previous or {}
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="",
        button_payload=payload,
        collected_data=previous.get("collected_data", {}),
        pending_action_id=previous.get("pending_action_id"),
        patient_identity=previous.get("patient_identity"),
    )
    return await graph.ainvoke(state, config=config)


@pytest.mark.asyncio
async def test_reminder_reschedule_tap_shows_slots_and_reschedules_the_same_appointment():
    graph, gateway, appointment_id = await _build()

    shown = await _tap(graph, f"REMINDER_RESCHEDULE:{appointment_id}")

    assert shown["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert [row.id for row in shown["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-new"
    ]

    proposed = await _tap(graph, f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-new", shown)

    assert proposed["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert proposed["pending_action_id"] is not None

    done = await _tap(graph, CONFIRM_APPOINTMENT_PAYLOAD, proposed)

    assert done["collected_data"] == {"post_action_context": "reschedule_appointment"}
    mine = await gateway.get_patient_appointments("pat-1")
    assert [str(a.id) for a in mine] == [appointment_id]
    assert mine[0].slot.id == "slot-new"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["cancelled", "attended", "no_show"])
async def test_reminder_reschedule_tap_on_a_closed_appointment_gives_the_stale_text(state):
    graph, gateway, appointment_id = await _build(reminder_state=state)

    result = await _tap(graph, f"REMINDER_RESCHEDULE:{appointment_id}")

    assert result["response_text"] == STALE
    assert result.get("response_list") is None
    assert (await gateway.get_patient_appointments("pat-1"))[0].slot.id == "slot-old"
