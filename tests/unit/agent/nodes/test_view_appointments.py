"""'Ver mi cita' shows an appointment summary and offers actions, instead of
being routed as a reschedule."""

import pytest

from app.agent.nodes.appointment import (
    _OPERATION_BY_MENTION,
    _OPERATION_BY_PAYLOAD,
    CANCEL_APPOINTMENT_ACTION,
    OPERATION_VIEW_PAYLOAD,
    RESCHEDULE_APPOINTMENT_ACTION,
    STAGE_AWAITING_APPOINTMENT_SELECTION,
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_VIEW_ACTION,
    VIEW_APPOINTMENTS_ACTION,
    VIEW_CANCEL_PAYLOAD,
    VIEW_RESCHEDULE_PAYLOAD,
    _appointment_button,
)
from app.agent.nodes.appointment_selection import spanish_weekday
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.menu_payloads import MENU_MAIN_PAYLOAD
from app.domain.value_objects.welcome_menu import WELCOME_TEXT
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.seed_objects import make_patient, make_professional, make_specialty
from tests.unit.agent.nodes.test_appointment_node import (
    _PATIENT_PRIMITIVES,
    _future_slot,
    _make_node_and_conversation,
)

_VIEW_BUTTON_IDS = [VIEW_RESCHEDULE_PAYLOAD, VIEW_CANCEL_PAYLOAD, MENU_MAIN_PAYLOAD]


async def _book(gateway, *slots):
    return [
        await gateway.create_appointment(
            patient=make_patient(id_="pat-1"), slot=slot, idempotency_key=f"seed-{slot.id}"
        )
        for slot in slots
    ]


def _view_state(**overrides):
    collected_data = {
        "stage": STAGE_AWAITING_IDENTIFICATION,
        "operation": VIEW_APPOINTMENTS_ACTION,
    }
    return make_agent_state(
        conversation_id="conv-1",
        user_message=overrides.pop("user_message", "Juan Perez, 30123456"),
        collected_data=overrides.pop("collected_data", collected_data),
        **overrides,
    )


async def _summary_for(node, gateway, *slots):
    appointments = await _book(gateway, *slots)
    result = await node(_view_state())
    return appointments, result


class _IntroLLM(FakeLLMProvider):
    """Records the intents asked and answers the summary intro with a fixed line."""

    def __init__(self) -> None:
        super().__init__()
        self.intents: list[str] = []

    async def generate_response(self, context):
        self.intents.append(context.intent)
        if context.intent == "view_appointments_summary":
            return "Estos son tus próximos turnos:"
        return await super().generate_response(context)


def test_view_maps_to_its_own_operation_for_both_the_button_and_the_typed_mention():
    assert _OPERATION_BY_PAYLOAD[OPERATION_VIEW_PAYLOAD] == VIEW_APPOINTMENTS_ACTION
    assert _OPERATION_BY_MENTION["view"] == VIEW_APPOINTMENTS_ACTION
    assert VIEW_APPOINTMENTS_ACTION not in (
        RESCHEDULE_APPOINTMENT_ACTION,
        CANCEL_APPOINTMENT_ACTION,
    )


@pytest.mark.asyncio
async def test_the_welcome_lists_view_row_reaches_identification_as_a_view_not_a_reschedule():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_VIEW_PAYLOAD,
            collected_data={},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == VIEW_APPOINTMENTS_ACTION


@pytest.mark.asyncio
async def test_a_typed_view_request_reaches_identification_as_a_view():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="qué turnos tengo?",
            collected_data={"operation_mention": "view"},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == VIEW_APPOINTMENTS_ACTION


@pytest.mark.asyncio
async def test_viewing_shows_the_summary_and_three_actions_without_starting_a_reschedule():
    slot = _future_slot()
    node, _, gateway = await _make_node_and_conversation(
        available_slots=[slot],
        professionals=[make_professional(id_="prof-1", full_name="Dra. Ana", specialty_id="ortho")],
        specialties=[make_specialty(id_="ortho", name="Ortodoncia")],
        llm_provider=_IntroLLM(),
    )

    appointments, result = await _summary_for(node, gateway, slot)

    start = appointments[0].slot.time_range.start
    line = (
        f"- {spanish_weekday(start)} {start.strftime('%d/%m')}, {start.strftime('%H:%M')} "
        "— Dra. Ana (Ortodoncia)"
    )
    assert result["response_text"] == f"Estos son tus próximos turnos:\n\n{line}"
    assert [button.id for button in result["response_buttons"]] == _VIEW_BUTTON_IDS
    assert [button.title for button in result["response_buttons"]] == [
        "🔄 Reagendar",
        "❌ Cancelar",
        "Menú principal",
    ]
    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_VIEW_ACTION
    assert data["patient_appointments"] == appointments
    assert data["professional_names"] == {"prof-1": "Dra. Ana"}
    assert "rescheduling_appointment_id" not in data


@pytest.mark.asyncio
async def test_the_summary_intro_falls_back_to_static_copy_when_the_llm_fails():
    from app.infrastructure.llm.exceptions import LLMProviderError

    class _FailingLLM(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMProviderError("down")

    slot = _future_slot()
    node, _, gateway = await _make_node_and_conversation(
        available_slots=[slot], llm_provider=_FailingLLM()
    )

    _, result = await _summary_for(node, gateway, slot)

    intro, _, lines = result["response_text"].partition("\n\n")
    assert intro == "Estos son tus próximos turnos:"
    assert lines.startswith("- ")


@pytest.mark.asyncio
async def test_the_specialty_is_omitted_when_the_professional_has_none():
    slot = _future_slot()
    node, _, gateway = await _make_node_and_conversation(
        available_slots=[slot],
        professionals=[make_professional(id_="prof-1", full_name="Dra. Ana", specialty_id=None)],
    )

    _, result = await _summary_for(node, gateway, slot)

    assert result["response_text"].endswith("— Dra. Ana")


@pytest.mark.asyncio
async def test_a_long_list_is_capped_and_says_how_many_more_there_are():
    slots = [_future_slot(id_=f"slot-{n}", days=n) for n in range(1, 6)]
    node, _, gateway = await _make_node_and_conversation(available_slots=slots)

    appointments, result = await _summary_for(node, gateway, *slots)

    text = result["response_text"]
    assert text.count("\n- ") == 3
    assert "2 turnos más" in text
    assert len(result["collected_data"]["patient_appointments"]) == 3
    assert result["collected_data"]["patient_appointments"] == appointments[:3]


@pytest.mark.asyncio
async def test_a_remembered_patient_skips_identification_and_gets_the_summary():
    slot = _future_slot()
    node, _, gateway = await _make_node_and_conversation(available_slots=[slot])
    await _book(gateway, slot)

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_VIEW_PAYLOAD,
            collected_data={"patient": _PATIENT_PRIMITIVES},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VIEW_ACTION


@pytest.mark.asyncio
async def test_viewing_with_no_appointments_keeps_the_no_appointments_reply():
    node, _, _ = await _make_node_and_conversation()

    result = await node(_view_state())

    assert result["response_text"] == "[fake-response for intent=no_appointments]"
    assert result["collected_data"] == {"patient": _PATIENT_PRIMITIVES}


async def _awaiting_view_action(*days: int, llm=None):
    slots = [_future_slot(id_=f"slot-{n}", days=n) for n in days]
    node, repository, gateway = await _make_node_and_conversation(
        available_slots=slots, llm_provider=llm
    )
    _, shown = await _summary_for(node, gateway, *slots)
    return node, repository, shown["collected_data"]


def _action_state(collected_data, **kwargs):
    return make_agent_state(conversation_id="conv-1", collected_data=collected_data, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"button_payload": VIEW_RESCHEDULE_PAYLOAD},
        {"user_message": "reagendar"},
        {"user_message": "quiero reprogramar"},
    ],
)
async def test_reschedule_with_one_appointment_goes_straight_to_the_next_slots(kwargs):
    node, _, data = await _awaiting_view_action(1)

    result = await node(_action_state(data, **kwargs))

    out = result["collected_data"]
    assert out["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert out.get("chosen_professional_id") is None
    assert result["response_list"].section_title == "Horarios disponibles"
    assert out["operation"] == RESCHEDULE_APPOINTMENT_ACTION
    assert out["rescheduling_appointment_id"] == str(data["patient_appointments"][0].id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"button_payload": VIEW_CANCEL_PAYLOAD}, {"user_message": "cancelar"}],
)
async def test_cancel_with_one_appointment_goes_straight_to_the_confirmation(kwargs):
    node, _, data = await _awaiting_view_action(1)

    result = await node(_action_state(data, **kwargs))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["operation"] == CANCEL_APPOINTMENT_ACTION
    assert result["pending_action_id"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,operation,intent",
    [
        (
            VIEW_RESCHEDULE_PAYLOAD,
            RESCHEDULE_APPOINTMENT_ACTION,
            "choose_appointment_to_reschedule",
        ),
        (VIEW_CANCEL_PAYLOAD, CANCEL_APPOINTMENT_ACTION, "choose_appointment_to_cancel"),
    ],
)
async def test_several_appointments_reuse_the_appointment_selection_step(
    payload, operation, intent
):
    node, _, data = await _awaiting_view_action(1, 2)
    appointments = data["patient_appointments"]

    result = await node(_action_state(data, button_payload=payload))

    out = result["collected_data"]
    assert out["stage"] == STAGE_AWAITING_APPOINTMENT_SELECTION
    assert out["operation"] == operation
    assert result["response_buttons"] == [_appointment_button(a) for a in appointments]
    assert f"intent={intent}" in result["response_text"]


@pytest.mark.asyncio
async def test_the_main_menu_button_resets_to_the_welcome_menu():
    node, _, data = await _awaiting_view_action(1)

    result = await node(_action_state(data, button_payload=MENU_MAIN_PAYLOAD))

    assert result["response_text"] == WELCOME_TEXT
    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_typed_main_menu_behaves_like_the_button():
    node, _, data = await _awaiting_view_action(1)

    result = await node(_action_state(data, user_message="menú principal"))

    assert result["response_text"] == WELCOME_TEXT
    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_unclear_text_shows_the_actions_again_and_keeps_the_stage():
    node, _, data = await _awaiting_view_action(1)

    result = await node(_action_state(data, user_message="jajaja no sé"))

    assert [button.id for button in result["response_buttons"]] == _VIEW_BUTTON_IDS
    assert result.get("collected_data", data)["stage"] == STAGE_AWAITING_VIEW_ACTION


@pytest.mark.asyncio
async def test_a_lost_view_context_restarts_instead_of_crashing():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        _action_state(
            {"stage": STAGE_AWAITING_VIEW_ACTION},
            button_payload=VIEW_RESCHEDULE_PAYLOAD,
        )
    )

    assert result["collected_data"] == {}
    assert result["response_buttons"] is None


@pytest.mark.asyncio
async def test_the_reschedule_entry_point_keeps_the_selection_step_with_new_framing():
    slot = _future_slot()
    intents: list[str] = []

    class _RecordingLLM(FakeLLMProvider):
        async def generate_response(self, context):
            intents.append(context.intent)
            assert "ver o reprogramar" not in str(context.collected_data)
            return await super().generate_response(context)

    node, _, gateway = await _make_node_and_conversation(
        available_slots=[slot], llm_provider=_RecordingLLM()
    )
    (appointment,) = await _book(gateway, slot)

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Juan Perez, 30123456",
            collected_data={
                "stage": STAGE_AWAITING_IDENTIFICATION,
                "operation": RESCHEDULE_APPOINTMENT_ACTION,
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_APPOINTMENT_SELECTION
    assert result["response_buttons"] == [_appointment_button(appointment)]
    assert "choose_appointment_to_reschedule" in intents


@pytest.mark.asyncio
async def test_the_summary_intro_is_requested_without_a_greeting_intent():
    llm = _IntroLLM()
    slot = _future_slot()
    node, conversation_repository, gateway = await _make_node_and_conversation(
        available_slots=[slot], llm_provider=llm
    )

    await _summary_for(node, gateway, slot)

    assert "view_appointments_summary" in llm.intents
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"
