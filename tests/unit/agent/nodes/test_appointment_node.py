from datetime import UTC, datetime, timedelta

import pytest

from app.agent.nodes.appointment import (
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
    STAGE_AWAITING_SLOT_SELECTION,
    _appointment_button,
    _slot_button,
    create_appointment_node,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_conversation_repository,
    make_dentalink_gateway,
    make_patient_gateway,
    make_proposal_repositories_provider,
)
from tests.fixtures.seed_objects import make_conversation, make_patient, make_pending_action

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
):
    conversation_repository = conversation_repository or make_conversation_repository()
    await conversation_repository.save(make_conversation(id_=conversation_id, mode="agent"))
    appointment_gateway = make_dentalink_gateway(
        available_slots=available_slots if available_slots is not None else [_future_slot()],
        professionals=professionals,
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
async def test_operation_menu_create_asks_for_identification():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert "DNI" in result["response_text"]


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
async def test_identification_stage_reports_when_patient_not_found():
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert "No encontramos ningún paciente" in result["response_text"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_identification_stage_offers_slots_once_patient_is_found():
    slot = _future_slot()
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES
    assert result["collected_data"]["available_slots"] == [slot]
    assert result["response_buttons"] == [_slot_button(slot)]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_identification_stage_offers_administracion_when_no_slots_available():
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
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
async def test_identification_stage_reports_not_found_for_reschedule_without_offering_creation():
    # A well-formed but unregistered DNI must NOT trigger a patient-creation
    # proposal for reschedule/cancel — there is nothing to reschedule for a
    # patient that doesn't exist yet.
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Maria Soto, 30111222",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "No encontramos ningún paciente" in result["response_text"]
    assert "collected_data" not in result
    assert "pending_action_id" not in result


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
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["patient"]["full_name"] == "Maria Soto"
    assert result["collected_data"]["patient"]["dni"] == "30111222"
    assert result["response_buttons"] == [_slot_button(slot)]
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
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
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
async def test_slot_selection_stage_proposes_the_appointment_on_a_valid_selection():
    slot = _future_slot()
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
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
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "patient": _PATIENT_PRIMITIVES,
            "available_slots": [slot],
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
