from datetime import UTC, datetime, timedelta

import pytest

from app.agent.nodes.appointment import (
    _ESCALATE_IDENTIFICATION_AFTER_ATTEMPTS,
    CANCEL_APPOINTMENT_ACTION,
    CONFIRM_APPOINTMENT_PAYLOAD,
    CREATE_APPOINTMENT_ACTION,
    CREATE_PATIENT_ACTION,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    REJECT_APPOINTMENT_PAYLOAD,
    RESCHEDULE_APPOINTMENT_ACTION,
    SELECT_APPOINTMENT_PAYLOAD_PREFIX,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_APPOINTMENT_SELECTION,
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_OPERATION_SELECTION,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    _appointment_button,
    create_appointment_node,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, MENU_APPOINTMENT_PAYLOAD
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_conversation_repository,
    make_dentalink_gateway,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import (
    make_conversation,
    make_patient,
    make_pending_action,
    make_professional,
    make_specialty,
)

_PATIENT_PRIMITIVES = {
    "id": "pat-1",
    "full_name": "Juan Perez",
    "phone": "+5491122334455",
    "dni": "30123456",
}


def _future_slot(
    id_: str = "slot-1", days: int = 1, professional_id: str = "prof-1"
) -> AppointmentSlot:
    now = datetime.now(UTC)
    start = now + timedelta(days=days)
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id="cleaning",
        time_range=DateTimeRange(start, start + timedelta(hours=1)),
    )


async def _make_node_and_conversation(
    available_slots=None,
    patients=None,
    conversation_repository=None,
    proposal_repositories_provider=None,
    professionals=None,
    conversation_id="conv-1",
    llm_provider=None,
    specialties=None,
):
    conversation_repository = conversation_repository or make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=conversation_id, mode="agent"))
    appointment_gateway = make_dentalink_gateway(
        available_slots=available_slots if available_slots is not None else [_future_slot()],
        professionals=professionals
        if professionals is not None
        else [make_professional(id_="prof-1", specialty_id="cleaning")],
    )
    node = create_appointment_node(
        appointment_gateway=appointment_gateway,
        patient_gateway=make_patient_gateway(
            patients=patients
            if patients is not None
            else [make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")]
        ),
        proposal_repositories_provider=(
            proposal_repositories_provider or make_proposal_repositories_provider()
        ),
        conversation_repository=conversation_repository,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        llm_provider=llm_provider or FakeLLMProvider(),
        specialty_gateway=make_specialty_gateway(
            specialties=specialties
            if specialties is not None
            else [make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
    )
    return node, conversation_repository, appointment_gateway


@pytest.mark.asyncio
async def test_first_turn_shows_the_operation_menu():
    node, _, _ = await _make_node_and_conversation()

    result = await node(make_agent_state(conversation_id="conv-1", collected_data={}))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_OPERATION_SELECTION
    assert "¿Qué querés hacer?" in result["response_text"]
    assert {b.id for b in result["response_buttons"]} == {
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_a_named_specialty_skips_straight_to_that_specialtys_doctors():
    # "quiero un turno de ortodoncia" already answered both menus, so the
    # patient must not be walked back through either of them.
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning")
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero un turno de ortodoncia",
        collected_data={"specialty_mention": "ortodoncia", "operation_mention": "create"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert "Dra. Laura Pérez" in result["response_text"]


@pytest.mark.asyncio
async def test_a_stated_operation_skips_the_operation_menu():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero sacar un turno",
        collected_data={"operation_mention": "create"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_a_stated_cancel_skips_to_identification():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero cancelar mi turno",
        collected_data={"operation_mention": "cancel"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == CANCEL_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_an_unmatched_specialty_mention_still_shows_the_menu():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero un turno de cardiología",
        collected_data={"specialty_mention": "cardiología"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_OPERATION_SELECTION


@pytest.mark.asyncio
async def test_operation_menu_reminds_on_unrecognized_input():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=None,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    result = await node(state)

    assert "collected_data" not in result
    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_operation_menu_reschedule_asks_for_identification():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_RESCHEDULE_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == RESCHEDULE_APPOINTMENT_ACTION
    assert "DNI" in result["response_text"]


@pytest.mark.asyncio
async def test_operation_menu_create_shows_the_numbered_specialty_list():
    # Booking now starts from the specialty, not from identification —
    # WhatsApp only allows 3 buttons, so a 16-specialty catalog has to be
    # a numbered text list the patient answers with a number.
    node, _, _ = await _make_node_and_conversation(
        specialties=[
            make_specialty(id_="cleaning", name="Ortodoncia"),
            make_specialty(id_="whitening", name="Endodoncia"),
        ]
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["response_buttons"] is None
    assert "1." in result["response_text"]
    assert "Ortodoncia" in result["response_text"]
    assert "2." in result["response_text"]
    assert "Endodoncia" in result["response_text"]


@pytest.mark.asyncio
async def test_specialty_selection_by_number_lists_that_specialtys_professionals():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning"),
            make_professional(id_="prof-9", full_name="Dr. Otro", specialty_id="whitening"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert "Dra. Laura Pérez" in result["response_text"]
    assert "Dr. Otro" not in result["response_text"]


@pytest.mark.asyncio
async def test_specialty_selection_by_name_also_works():
    # The patient in production typed "turno para ortodoncia" rather than
    # a number — same catalog-matching idiom agreement.py already uses.
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero ortodoncia por favor",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"


@pytest.mark.asyncio
async def test_specialty_selection_out_of_range_number_reprompts_same_list():
    node, _, _ = await _make_node_and_conversation()
    options = [make_specialty(id_="cleaning", name="Ortodoncia")]
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="99",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": options,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["specialty_retry_count"] == 1
    assert "Ortodoncia" in result["response_text"]


@pytest.mark.asyncio
async def test_specialty_selection_garbage_text_reprompts_same_list():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="asdkjasd",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["specialty_retry_count"] == 1


@pytest.mark.asyncio
async def test_stale_button_during_specialty_selection_is_treated_as_unrecognized():
    # These stages never send buttons, so any payload arriving here is a
    # tap on an older message still on the patient's phone.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_text"]


@pytest.mark.asyncio
async def test_specialty_with_no_professionals_dead_ends_gracefully():
    node, conversation_repository, _ = await _make_node_and_conversation(professionals=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert "administración" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_professional_selection_shows_only_that_doctors_slots():
    chosen = _future_slot(id_="slot-mine", professional_id="prof-1")
    other = _future_slot(id_="slot-theirs", professional_id="prof-9")
    node, _, _ = await _make_node_and_conversation(available_slots=[chosen, other])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert [b.id for b in result["response_buttons"]] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-mine"
    ]


@pytest.mark.asyncio
async def test_professional_selection_invalid_reprompts_same_list():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="nada que ver",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["professional_retry_count"] == 1


@pytest.mark.asyncio
async def test_slot_selection_in_the_create_flow_goes_to_identification():
    # Key regression test for the reordered flow: the patient sees value
    # (a real slot) before being asked for personal data.
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_professional_id": "prof-1",
            "available_slots": [slot],
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["pending_selected_slot"] == slot
    assert "pending_action_id" not in result
    assert "DNI" in result["response_text"]


@pytest.mark.asyncio
async def test_identification_after_slot_selection_proposes_the_chosen_slot():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot], proposal_repositories_provider=repositories_provider
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "pending_selected_slot": slot,
            "professional_names": {"prof-1": "Dra. Laura Pérez"},
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    async with repositories_provider() as repositories:
        pending = await repositories.pending_actions.get_by_id(result["pending_action_id"])
    assert pending is not None
    assert pending.action_type == CREATE_APPOINTMENT_ACTION
    # /v5/agendas never returns id_especialidad, so the specialty the
    # patient picked earlier is the only possible source for it.
    assert pending.payload["specialty_id"] == "cleaning"


@pytest.mark.asyncio
async def test_reschedule_and_cancel_still_ask_for_identification_first():
    # Reschedule/cancel start from "list YOUR appointments", which
    # Dentalink cannot answer without knowing the patient — so the
    # reordering is scoped to booking a new appointment only.
    for payload, action in (
        (OPERATION_RESCHEDULE_PAYLOAD, RESCHEDULE_APPOINTMENT_ACTION),
        (OPERATION_CANCEL_PAYLOAD, CANCEL_APPOINTMENT_ACTION),
    ):
        node, _, _ = await _make_node_and_conversation()
        state = make_agent_state(
            conversation_id="conv-1",
            button_payload=payload,
            collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
        )

        result = await node(state)

        assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
        assert result["collected_data"]["operation"] == action


@pytest.mark.asyncio
async def test_specialty_and_professional_stages_leave_free_input():
    node, conversation_repository, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    await node(state)

    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_slot_offer_never_exceeds_three_buttons():
    # WhatsApp caps interactive reply buttons at 3.
    slots = [_future_slot(id_=f"slot-{i}", days=i + 1) for i in range(6)]
    node, _, _ = await _make_node_and_conversation(available_slots=slots)
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await node(state)

    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_operation_menu_cancel_asks_for_identification():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CANCEL_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == CANCEL_APPOINTMENT_ACTION
    assert "DNI" in result["response_text"]


@pytest.mark.asyncio
async def test_identification_stage_reprompts_on_unparseable_text():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="hola quiero un turno",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert result["response_text"]
    assert result["collected_data"]["identification_retry_count"] == 1
    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION


@pytest.mark.asyncio
async def test_identification_stage_reprompt_text_varies_and_is_llm_generated():
    stub_text = "Mmm, no logré separar tu nombre del DNI. ¿Me lo pasás junto, tipo Juan Pérez?"

    class _StubLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            return stub_text

    node, _, _ = await _make_node_and_conversation(llm_provider=_StubLLMProvider())
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="hola quiero un turno",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert result["response_text"] == stub_text


@pytest.mark.asyncio
async def test_identification_stage_reprompt_falls_back_to_static_message_on_llm_failure():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(llm_provider=_ExplodingLLMProvider())
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="hola quiero un turno",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert "No pude leer" in result["response_text"]
    assert result["collected_data"]["identification_retry_count"] == 1


@pytest.mark.asyncio
async def test_an_unknown_patient_is_offered_registration_whatever_they_came_to_do():
    # Seen live: a patient wrote "voy a llegar más tarde", which reads as
    # rescheduling, so `operation` was never CREATE. When Dentalink did not
    # know them, the old code answered "no encontramos ningún paciente"
    # WITHOUT returning collected_data — leaving the stage on
    # identification forever. Every later message re-entered the parser and
    # got the same reprompt: an inescapable loop. The registration offer
    # existed all along, on the other side of that `if`.
    node, _, _ = await _make_node_and_conversation(
        patients=[], conversation_id="ycloud-+5491122334455"
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        user_message="Fernando Ariel, 35946257",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    assert [b.id for b in result["response_buttons"]] == [
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    ]
    # The data they gave is echoed back, so they can spot their own typo.
    assert "Fernando Ariel" in result["response_text"]
    assert "35946257" in result["response_text"]


@pytest.mark.asyncio
async def test_a_newly_registered_patient_with_no_chosen_slot_is_offered_specialties():
    # Registration reached from reschedule/cancel has no slot picked yet —
    # a brand-new patient has no appointments to reschedule either, so the
    # only useful next step is booking one. Proposing a slot that was never
    # chosen would dead-end on "se me perdió el hilo".
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        patients=[], proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        pending_action = make_pending_action(
            conversation_id="conv-1",
            action_type=CREATE_PATIENT_ACTION,
            payload={
                "full_name": "Fernando Ariel",
                "dni": "35946257",
                "phone": "+5491122334455",
            },
        )
        await repositories.pending_actions.save(pending_action)

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id=pending_action.id,
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert "se me perdió el hilo" not in result["response_text"].lower()


@pytest.mark.asyncio
async def test_a_main_menu_button_escapes_a_flow_the_patient_is_stuck_in():
    # Seen live: the patient tapped "Turnos" on the welcome menu while
    # trapped mid-identification, and the agent went right on asking for
    # their DNI. A main-menu tap is an unambiguous "start over" — it must
    # never be read as an answer to the question currently on screen.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=MENU_APPOINTMENT_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "identification_retry_count": 3,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_OPERATION_SELECTION
    # The stale counters from the abandoned flow must not leak forward.
    assert "identification_retry_count" not in result["collected_data"]


@pytest.mark.asyncio
async def test_identification_escalates_to_administration_after_repeated_misses():
    # Without a ceiling, `identification_retry_count` just counted upward
    # while the patient rewrote their DNI forever. The fallback node has
    # escalated after two misses all along; identification never did.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="no sé si estoy registrado",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "identification_retry_count": _ESCALATE_IDENTIFICATION_AFTER_ATTEMPTS,
        },
    )

    result = await node(state)

    assert result["response_buttons"] is not None
    assert MENU_ADMIN_PAYLOAD in [b.id for b in result["response_buttons"]]


@pytest.mark.asyncio
async def test_identification_stage_proposes_the_already_chosen_slot():
    # The slot is now picked BEFORE identification, so identifying is the
    # last step before the confirm/reject buttons — it must never search
    # availability again.
    slot = _future_slot()
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES
    assert result["pending_action_id"] is not None
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_professional_selection_offers_administracion_when_no_slots_available():
    # Availability is searched right after the doctor is chosen now, so
    # this is where an empty agenda surfaces.
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data={
            "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "professional_options": [make_professional(id_="prof-1")],
        },
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert "administración" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_identification_stage_reprompts_when_dni_shape_is_invalid():
    # "123456" matches `_DNI_PATTERN` (6-9 digits) but is too short for a
    # real Argentine DNI (7-8 digits) — must re-ask for just the DNI, not
    # fall through to "patient not found" or propose creating anyone.
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["response_text"]
    assert result["collected_data"]["identification_retry_count"] == 1
    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert "pending_action_id" not in result


@pytest.mark.asyncio
async def test_dni_invalid_reprompt_remembers_the_already_parsed_full_name():
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Ferdinando perez, 123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["identification_full_name"] == "Ferdinando perez"


@pytest.mark.asyncio
async def test_dni_invalid_reprompt_does_not_leak_a_stray_digit_into_the_remembered_name():
    # A DNI longer than 9 digits used to get truncated by the old
    # `_DNI_PATTERN` (capped at 9), leaving the extra digit stuck onto the
    # parsed name (e.g. "Ferdinando perez, 2") — seen live in production.
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Ferdinando perez, 3012121212",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["identification_full_name"] == "Ferdinando perez"


@pytest.mark.asyncio
async def test_identification_stage_combines_a_bare_dni_correction_with_the_remembered_name():
    # The patient already gave a valid name on the previous (DNI-invalid)
    # attempt; sending just the corrected DNI alone must not throw away
    # that name and ask for everything again.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "identification_full_name": "Juan Perez",
            "pending_selected_slot": _future_slot(),
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES


@pytest.mark.asyncio
async def test_bare_dni_message_without_a_remembered_name_still_reprompts_for_both():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="30123456",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert result["response_text"]
    assert result["collected_data"]["identification_retry_count"] == 1
    assert "patient" not in result.get("collected_data", {})


@pytest.mark.asyncio
async def test_dni_invalid_reprompt_falls_back_to_static_message_on_llm_failure():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(
        patients=[], llm_provider=_ExplodingLLMProvider()
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "DNI" in result["response_text"]
    assert "no parece válido" in result["response_text"]


@pytest.mark.asyncio
async def test_cancelling_an_unknown_patient_also_offers_registration():
    # This used to assert the opposite — that reschedule/cancel must NOT
    # offer to create the patient, "there is nothing to reschedule for a
    # patient that doesn't exist yet". True, and precisely why the old
    # branch dead-ended: it returned no `collected_data`, pinning the
    # patient in the identification stage forever. Registering them and
    # moving on to booking is the only exit that helps.
    node, _, _ = await _make_node_and_conversation(
        patients=[], conversation_id="ycloud-+5491122334455"
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        user_message="Maria Soto, 30111222",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None


@pytest.mark.asyncio
async def test_identification_stage_proposes_creating_a_new_patient_when_not_found():
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    node, conversation_repository, _ = await _make_node_and_conversation(
        patients=[],
        conversation_repository=conversation_repository,
        proposal_repositories_provider=repositories_provider,
        conversation_id="ycloud-+5491122334455",
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        user_message="Maria Soto, 30111222",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }
    assert "Maria Soto" in result["response_text"]
    assert "30111222" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+5491122334455"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"

    async with repositories_provider() as repositories:
        pending_action = await repositories.pending_actions.get_by_id(result["pending_action_id"])
        assert pending_action is not None
        assert pending_action.action_type == CREATE_PATIENT_ACTION
        # `phone` is derived from the WhatsApp contact's own identity
        # (`ConversationId` == "ycloud-{phone}"), never from parsed text.
        assert pending_action.payload == {
            "full_name": "Maria Soto",
            "dni": "30111222",
            "phone": "+5491122334455",
        }


@pytest.mark.asyncio
async def test_confirmation_stage_confirms_new_patient_creation_and_offers_slots():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    patient_gateway = make_patient_gateway(patients=[])
    appointment_gateway = make_dentalink_gateway(available_slots=[slot])
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="agent")
    )
    node = create_appointment_node(
        appointment_gateway=appointment_gateway,
        patient_gateway=patient_gateway,
        proposal_repositories_provider=repositories_provider,
        conversation_repository=conversation_repository,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        llm_provider=FakeLLMProvider(),
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
    )
    payload = {"full_name": "Maria Soto", "dni": "30111222", "phone": "+5491122334455"}
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1",
                conversation_id="ycloud-+5491122334455",
                action_type=CREATE_PATIENT_ACTION,
                status="pending",
                payload=payload,
            )
        )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    # The slot was already chosen before identification, so creating the
    # patient continues straight to confirming that exact slot.
    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["patient"]["full_name"] == "Maria Soto"
    assert result["collected_data"]["patient"]["dni"] == "30111222"
    assert result["pending_action_id"] is not None
    created = await patient_gateway.find_patient("Maria Soto", "30111222")
    assert created is not None
    assert str(created.phone) == "+5491122334455"


@pytest.mark.asyncio
async def test_confirmation_stage_rejects_new_patient_creation_proposal():
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, _ = await _make_node_and_conversation(
        patients=[], proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1",
                action_type=CREATE_PATIENT_ACTION,
                status="pending",
                payload={"full_name": "Maria Soto", "dni": "30111222", "phone": "+5491122334455"},
            )
        )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=REJECT_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] is None
    assert result["pending_action_id"] is None
    async with repositories_provider() as repositories:
        rejected = await repositories.pending_actions.get_by_id("pa-1")
        assert rejected is not None
        assert rejected.status == "cancelled"


@pytest.mark.asyncio
async def test_confirmation_stage_recovers_from_a_create_patient_race_and_never_duplicates():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    # Simulates another turn/request having already created this exact DNI
    # between the propose and the confirm (e.g. a retried/duplicated
    # confirm turn) — `create_patient` must raise `PatientAlreadyExistsError`
    # and the node must recover by reusing that record, never duplicating.
    existing_patient = make_patient(id_="pat-existing", full_name="Maria Soto", dni="30111222")
    patient_gateway = make_patient_gateway(patients=[existing_patient])
    appointment_gateway = make_dentalink_gateway(available_slots=[slot])
    await conversation_repository.save(
        make_conversation(id_="ycloud-+5491122334455", mode="agent")
    )
    node = create_appointment_node(
        appointment_gateway=appointment_gateway,
        patient_gateway=patient_gateway,
        proposal_repositories_provider=repositories_provider,
        conversation_repository=conversation_repository,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        llm_provider=FakeLLMProvider(),
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
    )
    payload = {"full_name": "Maria Soto", "dni": "30111222", "phone": "+5491122334455"}
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1",
                conversation_id="ycloud-+5491122334455",
                action_type=CREATE_PATIENT_ACTION,
                status="pending",
                payload=payload,
            )
        )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    # Recovered the PRE-EXISTING record (id="pat-existing"), never created
    # a second one for the same DNI.
    assert result["collected_data"]["patient"]["id"] == "pat-existing"


@pytest.mark.asyncio
async def test_slot_selection_stage_reminds_instead_of_advancing_on_free_text():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="el martes a las 10",
        button_payload=None,
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await node(state)

    assert "elegí uno de los horarios" in result["response_text"].lower()
    assert "collected_data" not in result
    assert len(result["response_buttons"]) == 1


@pytest.mark.asyncio
async def test_slot_selection_stage_reoffers_on_a_stale_button():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}unknown-slot",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await node(state)

    assert "ya no está disponible" in result["response_text"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_slot_selection_stage_proposes_immediately_when_rescheduling():
    # Reschedule identifies the patient up front (Dentalink cannot list
    # someone's appointments otherwise), so picking a new slot there goes
    # straight to confirmation — unlike the create flow, which asks for
    # identification at this point.
    slot = _future_slot()
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "apt-1",
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [slot],
            "professional_names": {},
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }
    assert "¿Confirmás" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_confirmation_stage_reminds_instead_of_advancing_on_free_text():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="si dale",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert "collected_data" not in result
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_confirmation_stage_rejects_the_pending_action():
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="pending"))

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=REJECT_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] is None
    assert result["pending_action_id"] is None
    assert "descartamos" in result["response_text"].lower()
    async with repositories_provider() as repositories:
        rejected = await repositories.pending_actions.get_by_id("pa-1")
        assert rejected is not None
        assert rejected.status == "cancelled"
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_confirmation_stage_confirms_and_creates_the_appointment():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[slot], proposal_repositories_provider=repositories_provider
    )
    payload = {
        "patient_id": "pat-1",
        "patient_full_name": "Juan Perez",
        "patient_phone": "+5491122334455",
        "patient_dni": "30123456",
        "slot_id": slot.id,
        "professional_id": slot.professional_id,
        "specialty_id": slot.specialty_id,
        "slot_start": slot.time_range.start.isoformat(),
        "slot_end": slot.time_range.end.isoformat(),
    }
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(id_="pa-1", status="pending", payload=payload)
        )

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert result["pending_action_id"] is None
    assert "confirmado" in result["response_text"].lower()
    assert appointment_gateway.get_appointment("1") is not None
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_confirmation_stage_reoffers_slots_when_the_slot_was_taken():
    slot = _future_slot()
    other_slot = _future_slot(id_="slot-2", days=2)
    repositories_provider = make_proposal_repositories_provider()
    # The gateway still has OTHER availability, but not `slot` itself —
    # simulates it being taken between "mostrar opciones" and "confirmar"
    # (PRD.md §11.2), while still letting `_offer_slots` show a fresh
    # option instead of falling through to the "no hay turnos" branch.
    node, conversation_repository, _ = await _make_node_and_conversation(
        available_slots=[other_slot], proposal_repositories_provider=repositories_provider
    )
    payload = {
        "patient_id": "pat-1",
        "patient_full_name": "Juan Perez",
        "patient_phone": "+5491122334455",
        "patient_dni": "30123456",
        "slot_id": slot.id,
        "professional_id": slot.professional_id,
        "specialty_id": slot.specialty_id,
        "slot_start": slot.time_range.start.isoformat(),
        "slot_end": slot.time_range.end.isoformat(),
    }
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(id_="pa-1", status="pending", payload=payload)
        )

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert "acaba de ocuparse" in result["response_text"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_confirmation_stage_offers_new_search_when_the_proposal_expired():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot], proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="expired"))

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "patient": _PATIENT_PRIMITIVES,
        },
    )

    result = await node(state)

    assert "ya no está vigente" in result["response_text"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION


@pytest.mark.asyncio
async def test_confirmation_stage_names_the_professional_when_available():
    slot = _future_slot(professional_id="prof-9")
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
            "professional_names": {"prof-9": "Dra. Laura Pérez"},
        },
    )

    result = await node(state)

    assert "Dra. Laura Pérez" in result["response_text"]


@pytest.mark.asyncio
async def test_identification_stage_offers_appointments_for_cancel():
    slot = _future_slot()
    node, _, appointment_gateway = await _make_node_and_conversation(available_slots=[slot])
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_APPOINTMENT_SELECTION
    assert result["collected_data"]["patient_appointments"] == [appointment]
    assert result["response_buttons"] == [_appointment_button(appointment)]


@pytest.mark.asyncio
async def test_identification_stage_reports_no_appointments_for_cancel():
    node, conversation_repository, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert "No encontramos turnos" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_appointment_selection_stage_reminds_instead_of_advancing_on_free_text():
    slot = _future_slot()
    node, _, appointment_gateway = await _make_node_and_conversation(available_slots=[slot])
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="el de mañana",
        button_payload=None,
        collected_data={
            "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "patient_appointments": [appointment],
            "professional_names": {},
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "elegí uno de tus turnos" in result["response_text"].lower()
    assert "collected_data" not in result
    assert len(result["response_buttons"]) == 1


@pytest.mark.asyncio
async def test_appointment_selection_stage_reoffers_on_a_stale_button():
    slot = _future_slot()
    node, _, appointment_gateway = await _make_node_and_conversation(available_slots=[slot])
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}unknown-appt",
        collected_data={
            "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "patient_appointments": [appointment],
            "professional_names": {},
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "ya no está disponible" in result["response_text"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_appointment_selection_stage_proposes_cancellation_on_a_valid_selection():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[slot], proposal_repositories_provider=repositories_provider
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}{appointment.id}",
        collected_data={
            "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "patient_appointments": [appointment],
            "professional_names": {},
            "operation": CANCEL_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    assert "cancelarlo" in result["response_text"].lower()
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }
    async with repositories_provider() as repositories:
        pending_action = await repositories.pending_actions.get_by_id(result["pending_action_id"])
        assert pending_action is not None
        assert pending_action.action_type == CANCEL_APPOINTMENT_ACTION
        assert pending_action.payload["appointment_id"] == str(appointment.id)
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_confirmation_stage_confirms_and_cancels_the_appointment():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[slot], proposal_repositories_provider=repositories_provider
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    payload = {
        "appointment_id": str(appointment.id),
        "patient_id": "pat-1",
        "professional_id": slot.professional_id,
        "slot_start": slot.time_range.start.isoformat(),
        "slot_end": slot.time_range.end.isoformat(),
    }
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1", status="pending", action_type=CANCEL_APPOINTMENT_ACTION, payload=payload
            )
        )

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert result["pending_action_id"] is None
    assert "cancelamos" in result["response_text"].lower()
    cancelled = appointment_gateway.get_appointment(str(appointment.id))
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_appointment_selection_stage_offers_new_slots_for_reschedule():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new", days=2)
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[new_slot]
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}{appointment.id}",
        collected_data={
            "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "patient_appointments": [appointment],
            "professional_names": {},
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["rescheduling_appointment_id"] == str(appointment.id)
    assert result["collected_data"]["available_slots"] == [new_slot]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_slot_selection_stage_proposes_reschedule_when_rescheduling():
    new_slot = _future_slot(id_="slot-new")
    node, conversation_repository, _ = await _make_node_and_conversation(
        available_slots=[new_slot]
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{new_slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [new_slot],
            "professional_names": {},
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert "reagendar" in result["response_text"].lower()
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_slot_selection_stage_proposal_carries_the_rescheduling_appointment_id():
    new_slot = _future_slot(id_="slot-new")
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[new_slot], proposal_repositories_provider=repositories_provider
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{new_slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [new_slot],
            "professional_names": {},
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
        },
    )

    result = await node(state)

    async with repositories_provider() as repositories:
        pending_action = await repositories.pending_actions.get_by_id(result["pending_action_id"])
        assert pending_action is not None
        assert pending_action.action_type == RESCHEDULE_APPOINTMENT_ACTION
        assert pending_action.payload["appointment_id"] == "appt-1"
        assert pending_action.payload["slot_id"] == new_slot.id


@pytest.mark.asyncio
async def test_confirmation_stage_confirms_and_reschedules_the_appointment():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new")
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[new_slot], proposal_repositories_provider=repositories_provider
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="seed-1"
    )
    payload = {
        "appointment_id": str(appointment.id),
        "slot_id": new_slot.id,
        "professional_id": new_slot.professional_id,
        "specialty_id": new_slot.specialty_id,
        "slot_start": new_slot.time_range.start.isoformat(),
        "slot_end": new_slot.time_range.end.isoformat(),
    }
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1",
                status="pending",
                action_type=RESCHEDULE_APPOINTMENT_ACTION,
                payload=payload,
            )
        )

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"] == {}
    assert result["pending_action_id"] is None
    assert "reagendamos" in result["response_text"].lower()
    rescheduled = appointment_gateway.get_appointment(str(appointment.id))
    assert rescheduled is not None
    assert rescheduled.slot == new_slot
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_confirmation_stage_reoffers_slots_when_the_new_slot_was_taken_for_reschedule():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new")
    other_slot = _future_slot(id_="slot-other", days=3)
    repositories_provider = make_proposal_repositories_provider()
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation(
        available_slots=[other_slot], proposal_repositories_provider=repositories_provider
    )
    appointment = await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="seed-1"
    )
    payload = {
        "appointment_id": str(appointment.id),
        "slot_id": new_slot.id,
        "professional_id": new_slot.professional_id,
        "specialty_id": new_slot.specialty_id,
        "slot_start": new_slot.time_range.start.isoformat(),
        "slot_end": new_slot.time_range.end.isoformat(),
    }
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(
                id_="pa-1",
                status="pending",
                action_type=RESCHEDULE_APPOINTMENT_ACTION,
                payload=payload,
            )
        )

    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "patient": _PATIENT_PRIMITIVES,
        },
    )

    result = await node(state)

    assert "acaba de ocuparse" in result["response_text"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    unchanged = appointment_gateway.get_appointment(str(appointment.id))
    assert unchanged is not None
    assert unchanged.slot == old_slot
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"
