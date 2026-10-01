import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

import app.agent.appointment_decision_subgraph as appointment_decision_subgraph
import app.agent.nodes.appointment as appointment
from app.agent.first_visit_intake_subgraph import (
    FIRST_VISIT_CANCEL_PAYLOAD,
    FIRST_VISIT_CONFIRM_PAYLOAD,
    FIRST_VISIT_REVIEW_CANCEL_PAYLOAD,
    FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
    FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
)
from app.agent.nodes.appointment import (
    _ESCALATE_IDENTIFICATION_AFTER_ATTEMPTS,
    _MAIN_MENU_RESET_MESSAGE,
    _VIEW_OTHER_PROFESSIONALS_PAYLOAD,
    CANCEL_APPOINTMENT_ACTION,
    CONFIRM_APPOINTMENT_PAYLOAD,
    CREATE_APPOINTMENT_ACTION,
    CREATE_PATIENT_ACTION,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
    REJECT_APPOINTMENT_PAYLOAD,
    RESCHEDULE_APPOINTMENT_ACTION,
    RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD,
    RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD,
    SELECT_APPOINTMENT_PAYLOAD_PREFIX,
    SELECT_SLOT_PAYLOAD_PREFIX,
    STAGE_AWAITING_APPOINTMENT_SELECTION,
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_NEW_PATIENT_DETAILS,
    STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
    STAGE_AWAITING_NO_SLOTS_CHOICE,
    STAGE_AWAITING_OPERATION_SELECTION,
    STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_REGISTRATION_FLOW,
    STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE,
    STAGE_AWAITING_SLOT_SELECTION,
    STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    STAGE_AWAITING_VERIFICATION_CONFIRMATION,
    STAGE_AWAITING_VERIFICATION_FLOW,
    VIEW_APPOINTMENTS_ACTION,
    _appointment_button,
    create_appointment_node,
    should_use_appointment_decision_subgraph,
)
from app.domain.exceptions.errors import AgreementAlreadyLinkedError
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.flow_response import FLOW_RESPONSE_PAYLOAD_PREFIX
from app.domain.value_objects.menu_payloads import (
    CHOOSE_PROFESSIONAL_PAYLOAD,
    LIST_BACK_PAYLOAD,
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    PROFESSIONAL_PAYLOAD_PREFIX,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.database.fake_pending_action_repository import (
    FakePendingActionRepository,
)
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import (
    future_slot as _future_slot,
)
from tests.fixtures.appointment_node import (
    make_node_and_conversation as _make_node_and_conversation,
)
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_agreement_gateway,
    make_conversation_repository,
    make_dentalink_gateway,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
)
from tests.fixtures.seed_objects import (
    make_agreement,
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


@pytest.mark.asyncio
async def test_first_turn_shows_the_operation_menu():
    node, _, _ = await _make_node_and_conversation()

    result = await node(make_agent_state(conversation_id="conv-1", collected_data={}))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_OPERATION_SELECTION
    # Wording is now LLM-generated (varied on purpose) — just require a reply.
    assert result["response_text"]
    assert {b.id for b in result["response_buttons"]} == {
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
    }


_CONTACT_CONVERSATION_ID = "ycloud-+5491198765432"
_INTAKE_BULLETS_ALL = "- Nombre completo\n- DNI\n- Correo electrónico\n- Obra social\n- Plan"


class _IntakeLLM(FakeLLMProvider):
    """Fake LLM whose extraction understands the free-text intake fields the
    stock fake cannot (obra social and plan) and records every generated intent."""

    def __init__(self) -> None:
        super().__init__()
        self.intents: list[str] = []

    async def generate_response(self, context):
        self.intents.append(context.intent)
        if context.intent == "first_visit_question":
            return "Dale, es tu primera cita en Smiling Pilar? Confirmame así te registro."
        if context.intent == "first_visit_intake_ask":
            return "Necesito que me pases estos datos para registrarte."
        return await super().generate_response(context)

    async def extract_information(self, message, required_fields):
        from app.domain.repositories.llm_provider import ExtractionResult

        fields: dict[str, object] = {}
        text = message.strip()
        if "Unknown Health 42" in text:
            fields.update(obra_social="Unknown Health", plan="42")
        elif "OSDE 210" in text:
            fields.update(obra_social="OSDE", plan="210")
        elif text == "OSDE":
            fields.update(obra_social="OSDE")
        elif text == "210":
            fields.update(plan="210")
        base = await super().extract_information(message, required_fields)
        found = {**base.fields, **{k: v for k, v in fields.items() if k in required_fields}}
        if "Ana Pérez" in text and "nombre_completo" in required_fields:
            found["nombre_completo"] = "Ana Pérez"
        return ExtractionResult(
            fields=found, missing_fields=[f for f in required_fields if f not in found]
        )


async def _start_create(node, conversation_id="conv-1"):
    return await node(
        make_agent_state(
            conversation_id=conversation_id,
            button_payload=OPERATION_CREATE_PAYLOAD,
            collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
        )
    )


async def _confirm_first_visit(node, question, conversation_id="conv-1"):
    return await node(
        make_agent_state(
            conversation_id=conversation_id,
            button_payload=FIRST_VISIT_CONFIRM_PAYLOAD,
            collected_data=question["collected_data"],
        )
    )


async def _answer_as_existing_patient(
    node, question, identification="Juan Perez, 30123456", conversation_id="conv-1"
):
    """Cancel the first-visit question, then identify (name + DNI)."""
    ask = await node(
        make_agent_state(
            conversation_id=conversation_id,
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD,
            collected_data=question["collected_data"],
        )
    )
    return await node(
        make_agent_state(
            conversation_id=conversation_id,
            user_message=identification,
            collected_data=ask["collected_data"],
        )
    )


@pytest.mark.asyncio
async def test_create_operation_asks_the_first_visit_question_with_confirm_and_cancel_buttons():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)

    question = await _start_create(node)

    assert question["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert question["response_text"] == (
        "Dale, es tu primera cita en Smiling Pilar? Confirmame así te registro."
    )
    assert [(b.id, b.title) for b in question["response_buttons"]] == [
        (FIRST_VISIT_CONFIRM_PAYLOAD, "✅ Confirmar"),
        (FIRST_VISIT_CANCEL_PAYLOAD, "❌ Cancelar"),
    ]
    assert "- " not in question["response_text"]
    assert question.get("response_list") is None
    assert llm.intents == ["first_visit_question"]


@pytest.mark.asyncio
async def test_confirming_the_first_visit_question_asks_for_the_five_fields():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    question = await _start_create(node)
    llm.intents.clear()

    intake = await _confirm_first_visit(node, question)

    assert intake["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert intake["collected_data"]["first_visit_intake"]["stage"] == "collect"
    assert intake["response_buttons"] is None
    assert intake["response_text"] == (
        "Necesito que me pases estos datos para registrarte.\n\n" + _INTAKE_BULLETS_ALL
    )
    assert intake.get("response_list") is None
    assert llm.intents == ["first_visit_intake_ask"]


@pytest.mark.asyncio
async def test_first_visit_question_falls_back_to_static_text_with_buttons_when_llm_fails():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLM(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(llm_provider=_ExplodingLLM())

    question = await _start_create(node)

    assert [b.id for b in question["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert "primera" in question["response_text"].casefold()
    assert "hola" not in question["response_text"].casefold()
    assert "- " not in question["response_text"]


@pytest.mark.asyncio
async def test_first_visit_ask_falls_back_to_static_bullets_when_the_llm_fails():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLM(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(llm_provider=_ExplodingLLM())
    question = await _start_create(node)

    intake = await _confirm_first_visit(node, question)

    assert intake["response_buttons"] is None
    assert intake["response_text"].endswith(_INTAKE_BULLETS_ALL)
    assert "hola" not in intake["response_text"].casefold()
    assert "primera" not in intake["response_text"].casefold()


@pytest.mark.asyncio
async def test_cancelling_the_first_visit_question_asks_for_name_and_dni_before_specialties():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    question = await _start_create(node)
    llm.intents.clear()

    ask = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD,
            collected_data=question["collected_data"],
        )
    )

    assert ask["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert ask["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert llm.intents == ["ask_identification"]
    assert ask.get("response_list") is None
    assert "first_visit_intake" not in ask["collected_data"]


@pytest.mark.asyncio
async def test_a_verified_existing_patient_then_gets_the_specialties():
    node, _, _ = await _make_node_and_conversation()
    question = await _start_create(node)

    result = await _answer_as_existing_patient(node, question)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["first_visit_completed"] is True
    assert result["collected_data"]["patient"]["dni"] == "30123456"
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_cancelling_with_name_and_dni_already_known_verifies_without_asking_again():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    question = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Puedo sacar uno ?",
            collected_data={
                "operation_mention": "create",
                "identification_full_name": "Juan Perez",
                "identification_dni": "30123456",
            },
        )
    )
    assert question["response_buttons"] is not None
    llm.intents.clear()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD,
            collected_data=question["collected_data"],
        )
    )

    assert "ask_identification" not in llm.intents
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["first_visit_completed"] is True
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_cancelling_when_the_patient_is_not_in_dentalink_offers_registration():
    node, _, _ = await _make_node_and_conversation(patients=[])
    question = await _start_create(node)

    result = await _answer_as_existing_patient(node, question)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert result.get("response_list") is None


@pytest.mark.parametrize("reply", ["sí, es la primera", "no soy paciente", "Confirmar"])
@pytest.mark.asyncio
async def test_a_free_text_first_visit_answer_behaves_like_the_confirm_button(reply):
    node, _, _ = await _make_node_and_conversation(llm_provider=_IntakeLLM())
    question = await _start_create(node)

    intake = await node(
        make_agent_state(
            conversation_id="conv-1", user_message=reply, collected_data=question["collected_data"]
        )
    )

    assert intake["collected_data"]["first_visit_intake"]["stage"] == "collect"
    assert intake["response_text"].endswith(_INTAKE_BULLETS_ALL)


@pytest.mark.asyncio
async def test_a_first_visit_reply_with_inline_details_only_asks_the_missing_fields():
    node, _, _ = await _make_node_and_conversation(llm_provider=_IntakeLLM())
    question = await _start_create(node)

    intake = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="sí, es la primera, soy Ana Pérez ana@example.com",
            collected_data=question["collected_data"],
        )
    )

    assert intake["collected_data"]["first_visit_intake"]["stage"] == "collect"
    assert intake["response_text"].endswith("- DNI\n- Obra social\n- Plan")
    assert "Nombre completo" not in intake["response_text"]
    assert "Correo electrónico" not in intake["response_text"]


@pytest.mark.asyncio
async def test_an_existing_patient_reply_with_name_and_dni_is_verified_without_asking_again():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(
        llm_provider=llm,
        patients=[make_patient(id_="pat-2", full_name="Ana Pérez", dni="30123457")],
    )
    question = await _start_create(node)
    llm.intents.clear()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="ya soy paciente, Ana Pérez 30123457",
            collected_data=question["collected_data"],
        )
    )

    assert "ask_identification" not in llm.intents
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["patient"]["dni"] == "30123457"


@pytest.mark.parametrize("reply", ["Cancelar", "Confirmar"])
@pytest.mark.asyncio
async def test_button_words_typed_during_collection_do_not_leave_the_intake(reply):
    node, _, _ = await _make_node_and_conversation(llm_provider=_IntakeLLM())
    intake = await _confirm_first_visit(node, await _start_create(node))

    result = await node(
        make_agent_state(
            conversation_id="conv-1", user_message=reply, collected_data=intake["collected_data"]
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"]["first_visit_intake"]["stage"] == "collect"


@pytest.mark.parametrize("reply", ["no, ya soy paciente", "no", "Cancelar"])
@pytest.mark.asyncio
async def test_a_free_text_existing_patient_answer_behaves_like_the_cancel_button(reply):
    node, _, _ = await _make_node_and_conversation(llm_provider=_IntakeLLM())
    question = await _start_create(node)

    ask = await node(
        make_agent_state(
            conversation_id="conv-1", user_message=reply, collected_data=question["collected_data"]
        )
    )

    assert ask["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert ask.get("response_list") is None


@pytest.mark.asyncio
async def test_an_unclear_first_visit_answer_asks_the_question_again_with_the_buttons():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    question = await _start_create(node)
    llm.intents.clear()

    again = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="quizás",
            collected_data=question["collected_data"],
        )
    )

    assert llm.intents == ["first_visit_question"]
    assert [b.id for b in again["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert again["collected_data"]["first_visit_intake"]["stage"] == "question"
    assert again.get("response_list") is None


@pytest.mark.asyncio
async def test_a_verified_patient_confirmation_without_a_slot_continues_to_specialties():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_VERIFICATION_CONFIRMATION,
                "operation": CREATE_APPOINTMENT_ACTION,
                "patient": _PATIENT_PRIMITIVES,
                "verified_patient_id": "pat-1",
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["first_visit_completed"] is True


@pytest.mark.asyncio
async def test_asking_to_book_after_a_reschedule_without_appointments_reuses_name_and_dni():
    # Regression, seen live: reschedule -> name + DNI -> "no encontramos turnos" ->
    # "Puedo sacar uno ?" got a static greeting + first-visit buttons that ignored
    # the identification the patient had just given.
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    no_appointments = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Juan Perez, 30123456",
            collected_data={
                "stage": STAGE_AWAITING_IDENTIFICATION,
                "operation": RESCHEDULE_APPOINTMENT_ACTION,
            },
        )
    )
    llm.intents.clear()

    question = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Puedo sacar uno ?",
            collected_data={**no_appointments["collected_data"], "operation_mention": "create"},
        )
    )
    assert llm.intents == ["first_visit_question"]
    llm.intents.clear()
    result = await _confirm_first_visit(node, question)

    assert llm.intents == ["first_visit_intake_ask"]
    assert result["response_buttons"] is None
    assert result["response_text"].endswith("- Correo electrónico\n- Obra social\n- Plan")
    assert "Nombre completo" not in result["response_text"]
    assert "DNI" not in result["response_text"]
    assert "hola" not in result["response_text"].casefold()
    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE


@pytest.mark.asyncio
async def test_partial_intake_reply_re_asks_only_the_missing_fields():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    intake = await _confirm_first_visit(node, await _start_create(node))

    collecting = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Es mi primera vez, soy Ana Pérez, ana@example.com",
            collected_data=intake["collected_data"],
        )
    )

    assert collecting["collected_data"]["first_visit_intake"]["stage"] == "collect"
    assert collecting["response_text"].endswith("- DNI\n- Obra social\n- Plan")
    assert "Correo electrónico" not in collecting["response_text"]
    assert collecting["response_buttons"] is None


_ALREADY_LINKED_NOTICE = (
    "Ya figurás en nuestro sistema con esa obra social, así que seguimos con tu turno."
)
_NO_ERROR_WORDS = ("error", "falló", "pendiente", "no pudimos")


def _assert_notice_then_same_next_step(result, success):
    assert result["response_text"] == f"{_ALREADY_LINKED_NOTICE}\n\n{success['response_text']}"
    assert result["response_buttons"] == success["response_buttons"]
    assert result.get("response_list") == success.get("response_list")
    assert result["collected_data"].get("stage") == success["collected_data"].get("stage")
    lowered = result["response_text"].casefold()
    assert not any(word in lowered for word in _NO_ERROR_WORDS)


async def _complete_new_patient_intake(node, coverage: str = "OSDE 210"):
    result = await _confirm_first_visit(
        node, await _start_create(node, _CONTACT_CONVERSATION_ID), _CONTACT_CONVERSATION_ID
    )
    result = await node(
        make_agent_state(
            conversation_id=_CONTACT_CONVERSATION_ID,
            user_message=f"Es mi primera vez. Ana Pérez, DNI 30123457, ana@example.com, {coverage}",
            collected_data=result["collected_data"],
        )
    )
    assert result["collected_data"]["first_visit_intake"]["stage"] == "review"
    for value in ("Ana Pérez", "30123457", "ana@example.com"):
        assert value in result["response_text"]
    return await node(
        make_agent_state(
            conversation_id=_CONTACT_CONVERSATION_ID,
            button_payload=FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
            collected_data=result["collected_data"],
        )
    )


def _legacy_intake_collected_data(stage: str, editing_field: str | None = None):
    """Intake state checkpointed under the old schema (phone + merged coverage)."""
    return {
        "operation": "create_appointment",
        "stage": STAGE_AWAITING_FIRST_VISIT_INTAKE,
        "first_visit_intake": {
            "stage": stage,
            "editing_field": editing_field,
            "details": {
                "full_name": "Ana Pérez",
                "dni": "30123457",
                "phone": "+5491198765432",
                "coverage": "OSDE 210",
            },
        },
    }


@pytest.mark.asyncio
async def test_legacy_checkpointed_review_confirm_asks_for_the_missing_fields_instead_of_failing():
    patient_gateway = make_patient_gateway(patients=[])
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=make_agreement_gateway(
            agreements=[make_agreement(id_="osde", name="OSDE")]
        ),
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    result = await node(
        make_agent_state(
            conversation_id=_CONTACT_CONVERSATION_ID,
            button_payload=FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
            collected_data=_legacy_intake_collected_data("review"),
        )
    )

    assert result["collected_data"]["first_visit_intake"]["stage"] == "collect"
    assert result["response_text"].endswith("- Correo electrónico\n- Obra social\n- Plan")
    assert await patient_gateway.find_patient("Ana Pérez", "30123457") is None


@pytest.mark.parametrize("legacy_field", ["phone", "coverage"])
@pytest.mark.asyncio
async def test_legacy_checkpointed_editing_field_still_extracts_the_free_text_reply(legacy_field):
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=make_patient_gateway(patients=[]),
        agreement_gateway=make_agreement_gateway(
            agreements=[make_agreement(id_="osde", name="OSDE")]
        ),
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    result = await node(
        make_agent_state(
            conversation_id=_CONTACT_CONVERSATION_ID,
            user_message="ana@example.com, OSDE 210",
            collected_data=_legacy_intake_collected_data("collect", legacy_field),
        )
    )

    intake = result["collected_data"]["first_visit_intake"]
    assert intake["stage"] == "review"
    assert intake["details"]["email"] == "ana@example.com"
    assert intake["details"]["obra_social"] == "OSDE"
    assert "Correo electrónico: ana@example.com" in result["response_text"]


@pytest.mark.asyncio
async def test_confirmed_first_visit_creates_patient_links_insurer_then_offers_specialties():
    patient_gateway = make_patient_gateway(patients=[])
    agreement = make_agreement(id_="osde", name="OSDE")
    agreement_gateway = make_agreement_gateway(agreements=[agreement])
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=agreement_gateway,
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    result = await _complete_new_patient_intake(node)

    patient = await patient_gateway.find_patient("Ana Pérez", "30123457")
    assert patient is not None
    assert patient.phone.value == "+5491198765432"
    assert await agreement_gateway.get_patient_agreements(patient.id) == [agreement]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["insurance_provider"] == "OSDE"
    assert result["collected_data"]["insurance_plan"] == "210"
    assert result["collected_data"]["patient"]["id"] == patient.id


@pytest.mark.asyncio
async def test_confirmed_first_visit_persists_the_email_on_the_new_patient():
    patient_gateway = make_patient_gateway(patients=[])
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=make_agreement_gateway(
            agreements=[make_agreement(id_="osde", name="OSDE")]
        ),
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    await _complete_new_patient_intake(node)

    patient = await patient_gateway.find_patient("Ana Pérez", "30123457")
    assert patient is not None
    assert patient.email == "ana@example.com"


@pytest.mark.asyncio
async def test_first_visit_agreement_is_matched_on_the_obra_social_alone():
    # The plan must never take part in the match: with both "OSDE" and
    # "OSDE Binario" on file, obra social "OSDE" + plan "Binario 210" is OSDE.
    osde = make_agreement(id_="osde", name="OSDE")
    binario = make_agreement(id_="osde-binario", name="OSDE Binario")
    patient_gateway = make_patient_gateway(patients=[])
    agreement_gateway = make_agreement_gateway(agreements=[osde, binario])
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=agreement_gateway,
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=llm,
    )
    intake = await _confirm_first_visit(
        node,
        await _start_create(node, _CONTACT_CONVERSATION_ID),
        _CONTACT_CONVERSATION_ID,
    )
    intake_data = intake["collected_data"]
    for value in ("Ana Pérez", "30123457", "ana@example.com", "OSDE", "Binario 210"):
        if value == "Binario 210":
            llm_plan = value

            async def _plan_only(message, required_fields, _plan=llm_plan):
                from app.domain.repositories.llm_provider import ExtractionResult

                return ExtractionResult(fields={"plan": _plan}, missing_fields=[])

            llm.extract_information = _plan_only
        intake = await node(
            make_agent_state(
                conversation_id=_CONTACT_CONVERSATION_ID,
                user_message=value,
                collected_data=intake_data,
            )
        )
        intake_data = intake["collected_data"]
    assert intake_data["first_visit_intake"]["stage"] == "review"

    result = await node(
        make_agent_state(
            conversation_id=_CONTACT_CONVERSATION_ID,
            button_payload=FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
            collected_data=intake_data,
        )
    )

    patient = await patient_gateway.find_patient("Ana Pérez", "30123457")
    assert patient is not None
    assert await agreement_gateway.get_patient_agreements(patient.id) == [osde]
    assert result["collected_data"]["insurance_provider"] == "OSDE"
    assert result["collected_data"]["insurance_plan"] == "Binario 210"


@pytest.mark.asyncio
async def test_unmatched_first_visit_insurer_does_not_create_patient_or_advance():
    patient_gateway = make_patient_gateway(patients=[])
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=make_agreement_gateway(agreements=[]),
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    result = await _complete_new_patient_intake(node, coverage="Unknown Health 42")

    assert await patient_gateway.find_patient("Ana Pérez", "30123457") is None
    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    intake = result["collected_data"]["first_visit_intake"]
    assert intake["stage"] == "collect"
    assert intake["editing_field"] == "obra_social"
    assert "No encontramos esa obra social" in result["response_text"]


@pytest.mark.asyncio
async def test_agreement_link_failure_keeps_confirmed_intake_retryable():
    patient_gateway = make_patient_gateway(patients=[])
    agreement_gateway = make_agreement_gateway(agreements=[make_agreement(id_="osde", name="OSDE")])
    agreement_gateway.link_patient_agreement = AsyncMock(side_effect=RuntimeError("unavailable"))
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        patient_gateway=patient_gateway,
        agreement_gateway=agreement_gateway,
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )

    result = await _complete_new_patient_intake(node)

    assert await patient_gateway.find_patient("Ana Pérez", "30123457") is not None
    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"]["first_visit_intake"]["stage"] == "review"
    assert "no pudimos vincular" in result["response_text"].casefold()
    assert {button.id for button in result["response_buttons"]} == {
        FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
        FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
        FIRST_VISIT_REVIEW_CANCEL_PAYLOAD,
    }


_EXISTING_ID = "pat-existing"
_OSDE = make_agreement(id_="osde", name="OSDE")
_OTHER = make_agreement(id_="other", name="Swiss Medical")
_ADMIN_HINT = 'Si querés actualizar algún dato, escribí "administración".'
_NOTICE_ON_RECORD = (
    "Ya figurás en nuestro sistema, así que seguimos con tu turno. "
    'Si querés actualizar algún dato (por ejemplo tu obra social), escribí "administración".'
)
_NOTICE_LINKED_NOW = (
    "Ya figurás en nuestro sistema y te cargamos la obra social, así que seguimos con tu "
    f"turno. {_ADMIN_HINT}"
)


def _EXISTING_PATIENT_FACTORY(full_name, dni):
    return make_patient(id_=_EXISTING_ID, full_name=full_name, dni=dni)


class _RecordingAgreementGateway(FakeAgreementGateway):
    def __init__(self, *args, get_error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.link_calls: list[tuple[str, str]] = []
        self.get_error = get_error

    async def get_patient_agreements(self, patient_id):
        if self.get_error is not None:
            raise self.get_error
        return await super().get_patient_agreements(patient_id)

    async def link_patient_agreement(self, patient_id, agreement_id):
        self.link_calls.append((patient_id, agreement_id))
        await super().link_patient_agreement(patient_id, agreement_id)


def _recording_gateway(patient_agreements=None, link=None, get_error=None):
    gateway = _RecordingAgreementGateway(
        agreements=[_OSDE, _OTHER], patient_agreements=patient_agreements, get_error=get_error
    )
    if link is not None:
        gateway.link_patient_agreement = link
    return gateway


async def _first_visit_confirm_with_link(agreement_gateway=None, existing=False):
    patients = [_EXISTING_PATIENT_FACTORY("Ana Pérez", "30123457")] if existing else []
    node, _, _ = await _make_node_and_conversation(
        patients=patients,
        patient_gateway=make_patient_gateway(patients=patients),
        agreement_gateway=agreement_gateway or _recording_gateway(),
        conversation_id=_CONTACT_CONVERSATION_ID,
        llm_provider=_IntakeLLM(),
    )
    return await _complete_new_patient_intake(node)


@pytest.mark.asyncio
async def test_first_visit_already_linked_agreement_tells_the_patient_and_continues():
    success = await _first_visit_confirm_with_link()

    result = await _first_visit_confirm_with_link(
        _recording_gateway(link=AsyncMock(side_effect=AgreementAlreadyLinkedError("pat-1", "osde")))
    )

    _assert_notice_then_same_next_step(result, success)
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert "first_visit_intake" not in result["collected_data"]
    assert result["collected_data"]["insurance_provider"] == "OSDE"


@pytest.mark.asyncio
async def test_first_visit_generic_link_failure_still_shows_the_pending_message():
    result = await _first_visit_confirm_with_link(
        _recording_gateway(link=AsyncMock(side_effect=RuntimeError("down")))
    )

    assert "El alta quedó pendiente" in result["response_text"]
    assert _ALREADY_LINKED_NOTICE not in result["response_text"]
    assert {button.title for button in result["response_buttons"]} == {
        "✅ Reintentar",
        "✏️ Modificar",
        "❌ Cancelar",
    }


@pytest.mark.asyncio
async def test_main_menu_button_mid_stage_resets_and_shows_a_distinct_message():
    # Regression: this used to be indistinguishable from the very first
    # message's generic "Qué querés hacer?" — the patient just abandoned a
    # whole flow, so the reset deserves its own acknowledgement.
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(llm_provider=_ExplodingLLMProvider())
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Menú principal",
        button_payload=MENU_APPOINTMENT_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "specialty_options": [make_specialty(id_="cleaning", name="Ortodoncia")],
        },
    )

    result = await node(state)

    assert result["response_text"] == _MAIN_MENU_RESET_MESSAGE
    assert result["collected_data"] == {"stage": STAGE_AWAITING_OPERATION_SELECTION}
    assert {b.id for b in result["response_buttons"]} == {
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_a_welcome_list_operation_row_abandons_a_stale_stage_for_a_different_operation():
    # Regression, seen live: the same WhatsApp number had left a stale
    # `STAGE_AWAITING_IDENTIFICATION`/RESCHEDULE from an earlier test still
    # checkpointed (LangGraph's `thread_id` is the phone-derived
    # `conversation_id`, independent of any `Conversation` row) when the
    # welcome menu got resent and the patient tapped "Agendar una cita" —
    # only `MENU_APPOINTMENT_PAYLOAD`/`MENU_SPECIALTIES_PAYLOAD` reset the
    # stage, so the stale RESCHEDULE silently won and the patient was asked
    # to identify themselves, then shown THEIR EXISTING appointment instead
    # of ever being asked which specialty they wanted.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_operation_menu_forwards_recent_messages_and_contact_memory_to_the_llm():
    # Regression: `generate_or_fallback` calls used to build `ResponseContext`
    # with no conversation history at all, so the model had no way to know
    # it (or the patient) had just spoken — reliably re-greeting on
    # back-to-back replies (seen live: two consecutive messages both opened
    # with "Hola"). `AgentState["recent_messages"]`/`["contact_memory_summary"]`
    # must actually reach the LLM call, not just exist unused on the state.
    from app.domain.repositories.llm_provider import ResponseContext

    captured: list[ResponseContext] = []

    class _CapturingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            captured.append(context)
            return "ok"

    node, _, _ = await _make_node_and_conversation(llm_provider=_CapturingLLMProvider())
    recent = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola! Como estas?"},
    ]
    state = make_agent_state(
        conversation_id="conv-1",
        collected_data={},
        recent_messages=recent,
        contact_memory_summary="Paciente frecuente.",
    )

    await node(state)

    assert captured[0].recent_messages == recent
    assert captured[0].contact_memory == "Paciente frecuente."
    # Regression: the LLM-worded reply used to leave the 3 operation
    # buttons (Sacar turno/Reagendar/Cancelar) with no inviting text at
    # all — an explicit instruction to do so must reach the prompt.
    assert "instruccion" in captured[0].collected_data


def _assert_next_slots_screen(result, *, max_rows: int = 10) -> None:
    """The create flow shows slots only: no professional list, no professional names."""
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert result["collected_data"].get("professional_options") is None
    response_list = result["response_list"]
    assert response_list is not None
    assert response_list.section_title == "Horarios disponibles"
    assert 0 < len(response_list.rows) <= max_rows
    assert all(row.id.startswith(SELECT_SLOT_PAYLOAD_PREFIX) for row in response_list.rows)
    assert "profesional" not in result["response_text"].lower().replace("[fake-response", "")
    assert "Dra. Laura Pérez" not in result["response_text"]
    assert all("Laura" not in row.title for row in response_list.rows)


def _ortodoncia_node_kwargs(slot_count: int = 12):
    return {
        "specialties": [make_specialty(id_="cleaning", name="Ortodoncia")],
        "professionals": [
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning")
        ],
        "available_slots": [_future_slot(id_=f"slot-{i}") for i in range(slot_count)],
    }


@pytest.mark.asyncio
async def test_a_named_specialty_shows_the_next_ten_slots_not_a_professional_list():
    # Live bug (2026-10-01): "Quería un turno de ortodoncia" -> first-visit question ->
    # Cancelar -> name + DNI -> the agent asked "con qué profesional preferís atenderte".
    node, _, _ = await _make_node_and_conversation(**_ortodoncia_node_kwargs())
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Quería un turno de ortodoncia",
        collected_data={"specialty_mention": "ortodoncia", "operation_mention": "create"},
    )

    intake = await node(state)
    assert intake["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert intake.get("response_list") is None
    result = await _answer_as_existing_patient(node, intake)

    _assert_next_slots_screen(result)
    assert len(result["response_list"].rows) == 10
    assert "menú" in result["response_text"]
    assert "administración" in result["response_text"]


@pytest.mark.asyncio
async def test_a_known_patient_naming_a_specialty_gets_the_slots_immediately():
    node, _, _ = await _make_node_and_conversation(**_ortodoncia_node_kwargs(slot_count=3))
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Quería un turno de ortodoncia",
        collected_data={
            "specialty_mention": "ortodoncia",
            "operation_mention": "create",
            "first_visit_completed": True,
            "patient": _PATIENT_PRIMITIVES,
        },
    )

    result = await node(state)

    _assert_next_slots_screen(result)
    assert len(result["response_list"].rows) == 3


@pytest.mark.asyncio
async def test_a_slot_picked_after_naming_a_specialty_proposes_that_slot():
    node, _, _ = await _make_node_and_conversation(**_ortodoncia_node_kwargs(slot_count=3))
    shown = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="quiero un turno de ortodoncia",
            collected_data={
                "specialty_mention": "ortodoncia",
                "operation_mention": "create",
                "first_visit_completed": True,
                "patient": _PATIENT_PRIMITIVES,
            },
        )
    )

    picked = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=shown["response_list"].rows[1].id,
            collected_data=shown["collected_data"],
        )
    )

    assert picked["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert picked["collected_data"]["pending_selected_slot"].id == "slot-1"


@pytest.mark.asyncio
async def test_a_named_professional_goes_straight_to_that_professionals_slots():
    # "quiero un turno con el doctor Carlos Adahenao" already answers who the patient wants:
    # no specialty question and no professional list, straight to that doctor's slots.
    mine = _future_slot(id_="slot-mine", professional_id="prof-1")
    theirs = _future_slot(id_="slot-theirs", professional_id="prof-2")
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="implants", name="Implantología")],
        professionals=[
            make_professional(id_="prof-1", full_name="Carlos Adahenao", specialty_id="implants"),
            make_professional(id_="prof-2", full_name="Camila Perez", specialty_id="implants"),
        ],
        available_slots=[mine, theirs],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero un turno con el doctor Carlos adahenao",
        collected_data={"professional_mention": "Carlos Adahenao"},
    )

    intake = await node(state)
    result = await _answer_as_existing_patient(node, intake)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert result["collected_data"]["chosen_specialty_id"] == "implants"
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert result["collected_data"].get("professional_options") is None
    assert result["response_list"].section_title == "Horarios disponibles"
    assert [r.id for r in result["response_list"].rows if r.id.startswith("SELECT_SLOT")] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-mine"
    ]


@pytest.mark.asyncio
async def test_a_named_professional_without_slots_offers_the_specialtys_next_slots():
    other = _future_slot(id_="slot-other", professional_id="prof-2")
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="implants", name="Implantología")],
        professionals=[
            make_professional(id_="prof-1", full_name="Carlos Adahenao", specialty_id="implants"),
            make_professional(id_="prof-2", full_name="Camila Perez", specialty_id="implants"),
        ],
        available_slots=[other],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero un turno con el doctor Carlos adahenao",
        collected_data={
            "professional_mention": "Carlos Adahenao",
            "operation_mention": "create",
            "first_visit_completed": True,
            "patient": _PATIENT_PRIMITIVES,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"].get("chosen_professional_id") is None
    assert [r.id for r in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-other"
    ]
    assert result["response_list"].section_title == "Horarios disponibles"
    assert "Camila" not in result["response_text"]


@pytest.mark.asyncio
async def test_a_named_professional_never_renders_a_professional_list_for_the_llm():
    # The slots prompt must tell the model not to name professionals; the old
    # "choose_professional" prompt is never generated in the create flow.
    from app.domain.repositories.llm_provider import ResponseContext

    captured: list[ResponseContext] = []

    class _CapturingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context: ResponseContext) -> str:
            captured.append(context)
            return await super().generate_response(context)

    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="implants", name="Implantología")],
        professionals=[
            make_professional(id_="prof-1", full_name="Carlos Adahenao", specialty_id="implants")
        ],
        llm_provider=_CapturingLLMProvider(),
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero un turno con el doctor Carlos adahenao",
        collected_data={"professional_mention": "Carlos Adahenao"},
    )

    intake = await node(state)
    await _answer_as_existing_patient(node, intake)

    assert not any(context.intent == "choose_professional" for context in captured)
    slot_context = next(c for c in captured if c.intent == "choose_slot")
    assert "instruccion" in slot_context.collected_data


@pytest.mark.asyncio
async def test_a_stated_operation_skips_the_operation_menu():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero sacar un turno",
        collected_data={"operation_mention": "create"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_a_stated_reschedule_skips_to_identification():
    # T3(b) of the fallback-menu-buttons change: reschedule has no
    # dedicated button either — same coverage this file already has for a
    # stated "cancelar" (`test_a_stated_cancel_skips_to_identification`
    # above) and a stated "sacar un turno"
    # (`test_a_stated_operation_skips_the_operation_menu`), but reschedule
    # itself had no equivalent test.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="quiero reagendar",
        collected_data={"operation_mention": "reschedule"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == RESCHEDULE_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_the_welcome_lists_create_row_skips_the_operation_menu():
    # The welcome list's booking rows carry these exact payloads directly
    # (this session's own brief) — a first-ever tap must reach the same
    # place a stated "quiero sacar un turno" already does, with no stage
    # set yet at all.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION


@pytest.mark.asyncio
async def test_the_welcome_lists_view_row_reaches_identification_as_its_own_operation():
    # "Ver mi cita" is a read-only view with its own operation (it shows a
    # summary first), sharing only the identification step with RESCHEDULE.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_VIEW_PAYLOAD,
        collected_data={},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == VIEW_APPOINTMENTS_ACTION


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
async def test_a_stated_view_request_skips_to_identification_instead_of_specialties():
    # Regression, seen live: "Qué turnos tengo?" fell through
    # `_OPERATION_BY_MENTION` (no "view" key at all) and landed in
    # CREATE's own fresh-entry path, asking for a specialty instead of
    # asking for name+DNI to look the patient's existing appointments up.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="que turnos tengo?",
        collected_data={"operation_mention": "view"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["operation"] == VIEW_APPOINTMENTS_ACTION


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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE


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
    # Wording is now LLM-generated (varied on purpose) — just require a reply.
    assert result["response_text"]


@pytest.mark.asyncio
async def test_operation_menu_create_shows_the_numbered_specialty_list():
    # Booking now starts from the specialty, not from identification —
    # WhatsApp only allows 3 buttons, so a 16-specialty catalog has to be
    # a numbered text list the patient answers with a number.
    node, _, _ = await _make_node_and_conversation(
        specialties=[
            make_specialty(id_="cleaning", name="Ortodoncia"),
            make_specialty(id_="whitening", name="Endodoncia"),
        ],
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="whitening"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=OPERATION_CREATE_PAYLOAD,
        collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
    )

    intake = await node(state)
    result = await _answer_as_existing_patient(node, intake)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    # Selection itself is now a paginated interactive list, so the old
    # "Volver al Menú" escape button is gone — LIST_BACK navigates back.
    assert result["response_buttons"] is None
    assert result["response_list"] is not None
    assert "Ortodoncia" in result["response_list"].rows[0].title
    assert "Endodoncia" in result["response_list"].rows[1].title


@pytest.mark.asyncio
async def test_legacy_staffed_specialty_lookup_wrapper_returns_none_and_warns_on_error(
    monkeypatch, caplog
):
    gateway = AsyncMock()
    gateway.list_professionals.side_effect = RuntimeError("lookup failed")

    result = await appointment._staffed_specialty_ids_safe(gateway)

    assert result is None
    gateway.list_professionals.assert_awaited_once_with()
    assert any("failed or timed out" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_legacy_staffed_specialty_lookup_wrapper_times_out_and_completes_cancellation(
    monkeypatch,
):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_lookup(_gateway):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(appointment, "staffed_specialty_ids", blocking_lookup)
    monkeypatch.setattr(
        appointment,
        "_STAFFED_SPECIALTY_TIMEOUT",
        timedelta(milliseconds=1),
    )

    result = await appointment._staffed_specialty_ids_safe(object())

    assert result is None
    assert started.is_set()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_actual_create_route_shows_all_specialties_when_staffed_lookup_fails(monkeypatch):
    safe_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(appointment_decision_subgraph, "_staffed_specialty_ids_safe", safe_lookup)
    specialties = [
        make_specialty(id_="cleaning", name="Ortodoncia"),
        make_specialty(id_="whitening", name="Endodoncia"),
    ]
    node, _, appointment_gateway = await _make_node_and_conversation(
        specialties=specialties, professionals=[]
    )

    intake = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_CREATE_PAYLOAD,
            collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
        )
    )
    result = await _answer_as_existing_patient(node, intake)

    safe_lookup.assert_awaited_once_with(appointment_gateway)
    assert result["collected_data"]["specialty_options"] == specialties
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_legacy_specialty_and_professional_list_prompts_do_not_require_numbers():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning")
        ],
    )

    specialty_result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_CREATE_PAYLOAD,
            collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
        )
    )
    professional_result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="quiero un turno de ortodoncia",
            collected_data={"specialty_mention": "ortodoncia"},
        )
    )

    assert "número" not in specialty_result["response_text"].casefold()
    assert "número" not in professional_result["response_text"].casefold()


@pytest.mark.asyncio
async def test_specialty_selection_advances_directly_to_the_slot_list():
    # A valid specialty pick now lists its soonest slots across ALL
    # enabled professionals directly (this change — most patients are new
    # and don't know a professional by name, and doctor names/choice
    # shouldn't appear at this point at all), not straight on the
    # professional list.
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning"),
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert result["response_buttons"] is None
    assert result["response_list"] is not None
    assert "Dra. Laura Pérez" not in result["response_list"].rows[0].title


@pytest.mark.asyncio
async def test_a_stale_choose_professional_tap_shows_the_specialtys_next_slots():
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[
            make_professional(id_="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning"),
            make_professional(id_="prof-9", full_name="Dr. Otro", specialty_id="whitening"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CHOOSE_PROFESSIONAL_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert result["response_list"].section_title == "Horarios disponibles"
    assert [r.id for r in result["response_list"].rows] == ["SELECT_SLOT:slot-1"]


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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
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
    assert "Ortodoncia" in result["response_list"].rows[0].title


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
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
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
async def test_a_stale_choose_professional_tap_without_slots_offers_the_three_way_fallback():
    node, conversation_repository, _ = await _make_node_and_conversation(
        professionals=[], available_slots=[]
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CHOOSE_PROFESSIONAL_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
        },
    )

    result = await node(state)

    # The checkpoint already sits on the browse stage, so no state update is reported.
    browse = STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE
    assert result.get("collected_data", {}).get("stage", browse) == browse
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (LIST_BACK_PAYLOAD, "Otra especialidad"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
    ]
    assert result.get("response_list") is None
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


def _in_flight_professional_selection(**overrides):
    return {
        "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
        "operation": CREATE_APPOINTMENT_ACTION,
        "chosen_specialty_id": "cleaning",
        "chosen_specialty_name": "Ortodoncia",
        "professional_options": [make_professional(id_="prof-1")],
        **overrides,
    }


@pytest.mark.asyncio
async def test_an_in_flight_professional_selection_checkpoint_shows_the_specialtys_slots():
    # Old checkpoints kept `awaiting_professional_selection` with a professional list on
    # screen: the next message converts to the slots screen of the same specialty.
    chosen = _future_slot(id_="slot-mine", professional_id="prof-1")
    other = _future_slot(id_="slot-theirs", professional_id="prof-9")
    node, _, _ = await _make_node_and_conversation(available_slots=[chosen, other])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data=_in_flight_professional_selection(),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"].get("chosen_professional_id") is None
    assert result["collected_data"].get("professional_options") is None
    assert result["response_buttons"] is None
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-mine"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-old",
        f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-1",
        CONFIRM_APPOINTMENT_PAYLOAD,
    ],
)
async def test_any_reply_to_an_in_flight_professional_list_shows_slots_never_a_retry(payload):
    # Free text, a stale professional row, a current professional row or an unrelated button:
    # none of them re-prompts the professional list or counts as a retry.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="nada que ver",
        button_payload=payload,
        collected_data=_in_flight_professional_selection(),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert "professional_retry_count" not in result["collected_data"]
    assert result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_an_in_flight_professional_selection_without_slots_offers_the_fallback_buttons():
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data=_in_flight_professional_selection(),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE
    assert LIST_BACK_PAYLOAD in [b.id for b in result["response_buttons"]]
    assert CHOOSE_PROFESSIONAL_PAYLOAD not in [b.id for b in result["response_buttons"]]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_a_reschedule_professional_selection_still_handles_its_professional_list():
    # OUT OF SCOPE on purpose: "cambiar profesional" of a RESCHEDULE keeps its professional list.
    chosen = _future_slot(id_="slot-mine", professional_id="prof-1")
    node, _, _ = await _make_node_and_conversation(available_slots=[chosen])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data=_in_flight_professional_selection(
            operation=RESCHEDULE_APPOINTMENT_ACTION, rescheduling_appointment_id="appt-1"
        ),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-mine",
        LIST_BACK_PAYLOAD,
    ]


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
    # Wording is now LLM-generated (varied on purpose) — just require a reply.
    assert result["response_text"]


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

    intake = await node(state)
    await _answer_as_existing_patient(node, intake)

    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_slot_offer_renders_as_a_list_and_shows_more_than_three_slots():
    # Regression: slots used to render as reply buttons, capped at 3 by
    # WhatsApp — any 4th+ available slot simply never showed. A list
    # supports up to Meta's real 10-row cap instead (an in-flight professional-selection
    # checkpoint converts to the specialty's next slots).
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

    assert result["response_buttons"] is None
    # 6 slot rows on one page: the next-slots screen has no navigation row.
    assert len(result["response_list"].rows) == 6
    assert all(r.id.startswith(SELECT_SLOT_PAYLOAD_PREFIX) for r in result["response_list"].rows)


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
    # Wording is now LLM-generated (varied on purpose) — just require a reply.
    assert result["response_text"]


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

    # Not found -> a plain "no patient found" with register / retry / advisor
    # buttons; insurance and email are only asked inside the registration intake.
    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert result["collected_data"]["identification_full_name"] == "Fernando Ariel"
    assert result["collected_data"]["identification_dni"] == "35946257"
    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_new_patient_details_stage_asks_for_whichever_piece_is_missing():
    node, _, _ = await _make_node_and_conversation(
        patients=[], conversation_id="ycloud-+5491122334455"
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        user_message="OSDE",
        collected_data={
            "stage": STAGE_AWAITING_NEW_PATIENT_DETAILS,
            "new_patient_full_name": "Fernando Ariel",
            "new_patient_dni": "35946257",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_NEW_PATIENT_DETAILS
    assert result["collected_data"]["new_patient_obra_social"] == "OSDE"
    assert "mail" in result["response_text"].lower()


@pytest.mark.asyncio
async def test_new_patient_details_stage_proposes_creation_once_both_fields_arrive():
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        patients=[],
        conversation_id="ycloud-+5491122334455",
        proposal_repositories_provider=repositories_provider,
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        user_message="OSDE, fernando@gmail.com",
        collected_data={
            "stage": STAGE_AWAITING_NEW_PATIENT_DETAILS,
            "new_patient_full_name": "Fernando Ariel",
            "new_patient_dni": "35946257",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["pending_action_id"] is not None
    assert [b.id for b in result["response_buttons"]] == [
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    ]
    # The data they gave (across both stages) is echoed back, so they can
    # spot their own typo before it's created.
    assert "Fernando Ariel" in result["response_text"]
    assert "35946257" in result["response_text"]
    assert "OSDE" in result["response_text"]
    assert "fernando@gmail.com" in result["response_text"]
    async with repositories_provider() as repositories:
        pending_action = await repositories.pending_actions.get_by_id(result["pending_action_id"])
        assert pending_action is not None
        assert pending_action.payload["obra_social"] == "OSDE"
        assert pending_action.payload["email"] == "fernando@gmail.com"


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
    # escalated after two misses all along; identification never did. The
    # escalation offers a restart, not an administration escape hatch —
    # that button was removed from all appointment-flow messages.
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
    assert MENU_ADMIN_PAYLOAD not in [b.id for b in result["response_buttons"]]
    assert MENU_APPOINTMENT_PAYLOAD in [b.id for b in result["response_buttons"]]


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
async def test_a_professional_without_slots_in_the_create_flow_offers_the_fallback_buttons():
    # An empty agenda surfaces when the specialty's slots are searched: the create flow
    # offers another specialty / menu / administration, never "ver otros profesionales".
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data=_in_flight_professional_selection(),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE
    assert _VIEW_OTHER_PROFESSIONALS_PAYLOAD not in [b.id for b in result["response_buttons"]]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_a_reschedule_professional_without_slots_still_offers_other_professionals():
    # OUT OF SCOPE on purpose: the RESCHEDULE flow keeps "Otros profesionales".
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="1",
        collected_data=_in_flight_professional_selection(
            operation=RESCHEDULE_APPOINTMENT_ACTION, rescheduling_appointment_id="appt-1"
        ),
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_NO_SLOTS_CHOICE
    assert [(button.id, button.title) for button in result["response_buttons"]] == [
        (_VIEW_OTHER_PROFESSIONALS_PAYLOAD, "Otros profesionales"),
    ]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_no_availability_choice_stage_re_offers_main_menu_on_a_stale_tap():
    # Live bug: WhatsApp never disables a past interactive message, so a
    # patient can tap an OLD, already-superseded professional list after
    # landing here. This stage previously had no handler at all — the tap
    # fell through the entire dispatch chain to the generic "no stage yet"
    # fallback and produced the confusing top-level operation menu ("Sacar
    # turno / Reagendar / Cancelar") out of nowhere. Must instead tell the
    # patient the tap is stale and re-offer the one valid option.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{PROFESSIONAL_PAYLOAD_PREFIX}prof-stale",
        collected_data={"stage": STAGE_AWAITING_NO_AVAILABILITY_CHOICE},
    )

    result = await node(state)

    # `collected_data` is omitted from the return entirely — the stage
    # stays STAGE_AWAITING_NO_AVAILABILITY_CHOICE, so the patient gets
    # another chance at the one valid option instead of the stage being
    # silently discarded.
    assert "collected_data" not in result
    assert [(button.id, button.title) for button in result["response_buttons"]] == [
        (MENU_MAIN_PAYLOAD, "Menú principal"),
    ]
    assert result["response_text"] == "[fake-response for intent=stale_tap]"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "text"),
    [(_VIEW_OTHER_PROFESSIONALS_PAYLOAD, "Ver otros profesionales"), (None, "no entiendo")],
)
async def test_a_legacy_no_slots_choice_checkpoint_converts_to_the_slots_screen(payload, text):
    # An old create-flow checkpoint stored `awaiting_no_slots_choice` with the "Otros
    # profesionales" button: whatever arrives next shows the specialty's next slots instead
    # of a professional list.
    node, _, _ = await _make_node_and_conversation(
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="cleaning"),
        ],
        available_slots=[_future_slot(id_="slot-2", professional_id="prof-2")],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message=text,
        button_payload=payload,
        collected_data={
            "stage": STAGE_AWAITING_NO_SLOTS_CHOICE,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"].get("professional_options") is None
    assert [r.id for r in result["response_list"].rows] == [f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-2"]


@pytest.mark.asyncio
async def test_a_legacy_no_slots_choice_checkpoint_without_a_specialty_shows_the_specialties():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="no entiendo",
        collected_data={
            "stage": STAGE_AWAITING_NO_SLOTS_CHOICE,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


@pytest.mark.asyncio
async def test_a_reschedule_no_slots_choice_still_offers_other_professionals_on_button_tap():
    # Regression, seen live: the professional just confirmed to have zero availability
    # (prof-1) was re-listed among the "other professionals". OUT OF SCOPE on purpose: the
    # RESCHEDULE flow keeps this professional list.
    node, _, _ = await _make_node_and_conversation(
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="cleaning"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Ver otros profesionales",
        button_payload=_VIEW_OTHER_PROFESSIONALS_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_NO_SLOTS_CHOICE,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert [p.id for p in result["collected_data"]["professional_options"]] == ["prof-2"]


@pytest.mark.asyncio
async def test_a_reschedule_no_slots_choice_reminds_on_unrecognized_input():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="no entiendo",
        collected_data={
            "stage": STAGE_AWAITING_NO_SLOTS_CHOICE,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert "collected_data" not in result
    button_ids = [b.id for b in result["response_buttons"]]
    assert button_ids == [_VIEW_OTHER_PROFESSIONALS_PAYLOAD]


@pytest.mark.asyncio
async def test_a_navigation_to_the_professional_step_in_the_create_flow_shows_slots():
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        collected_data={
            "stage": STAGE_AWAITING_SLOT_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "navigation_target": "professional",
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
            "available_slots": [_future_slot()],
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["response_list"].section_title == "Horarios disponibles"


@pytest.mark.asyncio
async def test_a_repaired_identification_without_professional_slots_shows_next_slots():
    # Partial checkpoint repair (CREATE): the chosen professional has no slots, so the
    # specialty's next slots are shown instead of a professional list.
    other = _future_slot(id_="slot-other", professional_id="prof-2")
    node, _, _ = await _make_node_and_conversation(
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="cleaning"),
        ],
        available_slots=[other],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "chosen_specialty_id": "cleaning",
            "chosen_specialty_name": "Ortodoncia",
            "chosen_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert [r.id for r in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}slot-other"
    ]


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
async def test_identification_stage_reprompts_when_full_name_is_a_single_word():
    # "cassera" alone passes `_parse_identification`'s own syntax check
    # (some text plus a 6+ digit run) but isn't a full name — matching a
    # single token against Dentalink by name+DNI fails even for an
    # already-registered patient, and used to cascade into "no lo
    # encontramos" -> offering to create a duplicate record for someone
    # who already exists (seen live in production).
    node, _, _ = await _make_node_and_conversation(patients=[])
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="cassera 30313131",
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
async def test_identification_completes_across_two_messages_dni_then_name():
    # The graph must iterate instead of demanding both in one message:
    # DNI first, then a plain name-only reply completes identification.
    node, _, _ = await _make_node_and_conversation(
        patients=[make_patient(full_name="Pedro Cassera", dni="30313131")]
    )
    first_state = make_agent_state(
        conversation_id="conv-1",
        user_message="30313131",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    first_result = await node(first_state)

    assert first_result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert first_result["collected_data"]["identification_dni"] == "30313131"
    assert "identification_full_name" not in first_result["collected_data"]

    second_state = make_agent_state(
        conversation_id="conv-1",
        user_message="Pedro Cassera",
        collected_data=first_result["collected_data"],
    )

    second_result = await node(second_state)

    assert second_result["collected_data"].get("stage") != STAGE_AWAITING_IDENTIFICATION


@pytest.mark.asyncio
async def test_identification_completes_across_two_messages_name_then_dni():
    node, _, _ = await _make_node_and_conversation(
        patients=[make_patient(full_name="Pedro Cassera", dni="30313131")]
    )
    first_state = make_agent_state(
        conversation_id="conv-1",
        user_message="Pedro Cassera",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    first_result = await node(first_state)

    # A name-only answer, given first, must be remembered right away — not
    # discarded and asked for again once the DNI arrives on the next turn
    # (bug found live: "Pedro Cassera" then "30131313" used to lose the
    # name and re-ask for it, since this stage always knows any free text
    # is an identification answer, never ordinary chatter).
    assert first_result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert first_result["collected_data"]["identification_full_name"] == "Pedro Cassera"
    assert "identification_retry_count" not in first_result["collected_data"]

    second_state = make_agent_state(
        conversation_id="conv-1",
        user_message="30313131",
        collected_data=first_result["collected_data"],
    )

    second_result = await node(second_state)

    assert second_result["collected_data"].get("stage") != STAGE_AWAITING_IDENTIFICATION


@pytest.mark.asyncio
async def test_identification_stage_rejects_casual_chatter_as_a_name():
    # Live bug: replying to the bot's own small talk ("Cómo estás?") with
    # "Bien vos?" got registered as the patient's full name — neither
    # "bien" nor "vos" happened to be on the old hardcoded blocklist this
    # stage used to judge a name-only answer with. Name detection is now
    # LLM-judged (see `_extract_full_name`) instead of a fixed word list,
    # so it must reject this and re-prompt rather than accept it.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Bien vos?",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert "identification_full_name" not in result["collected_data"]
    assert result["collected_data"]["identification_retry_count"] == 1


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
async def test_bare_dni_message_without_a_remembered_name_asks_for_the_name():
    # A bare DNI is a real signal (a 6+ digit run), even with no name text
    # of its own — the graph should keep the DNI and ask for just the
    # missing piece, not throw it away and demand both again.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="30123456",
        collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
    )

    result = await node(state)

    assert result["response_text"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["identification_dni"] == "30123456"
    assert "identification_retry_count" not in result.get("collected_data", {})
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE


@pytest.mark.asyncio
async def test_identification_stage_offers_alternatives_when_the_patient_is_not_found():
    node, _, _ = await _make_node_and_conversation(
        patients=[], conversation_id="ycloud-+5491122334455"
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert result["collected_data"]["identification_full_name"] == "Maria Soto"
    assert result["collected_data"]["identification_dni"] == "30111222"
    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_confirmation_stage_confirms_new_patient_creation_and_offers_slots():
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    patient_gateway = make_patient_gateway(patients=[])
    appointment_gateway = make_dentalink_gateway(available_slots=[slot])
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
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
        agreement_gateway=make_agreement_gateway(),
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
async def test_confirmation_stage_links_obra_social_and_saves_email_on_new_patient():
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    patient_gateway = make_patient_gateway(patients=[])
    appointment_gateway = make_dentalink_gateway()
    agreement_gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
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
        agreement_gateway=agreement_gateway,
    )
    payload = {
        "full_name": "Maria Soto",
        "dni": "30111222",
        "phone": "+5491122334455",
        "obra_social": "OSDE",
        "email": "maria@gmail.com",
    }
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

    await node(state)

    created = await patient_gateway.find_patient("Maria Soto", "30111222")
    assert created is not None
    assert created.email == "maria@gmail.com"
    linked = await agreement_gateway.get_patient_agreements(created.id)
    assert [agreement.name for agreement in linked] == ["OSDE"]


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
async def test_confirmation_stage_treats_a_free_text_decline_like_the_cancel_button():
    # Seen live: "No gracias" typed as free text used to fall into the
    # generic "solo podés confirmar o cancelar tocando un botón" reminder
    # — the reply ended up SOUNDING like it accepted the decline while the
    # code still reattached Confirmar/Cancelar to it, since nothing had
    # actually rejected the proposal. Confirmar/Cancelar must never linger
    # on a message that isn't an outstanding proposal.
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
        user_message="No gracias",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] is None
    assert result["pending_action_id"] is None
    assert result["response_buttons"] is None
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
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
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
        agreement_gateway=make_agreement_gateway(),
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
async def test_create_patient_race_lost_stays_in_identification_stage_for_a_retry():
    # `create_patient` raised `PatientAlreadyExistsError` (the DNI is
    # already registered) but the recovery lookup by name+DNI found no
    # match (the patient typed an incomplete/mismatched name) — the
    # response text asks the patient to retype name+DNI, so the stage must
    # stay on identification for that reply to actually be parsed as the
    # retry it was asked for, instead of falling out of the flow (and
    # losing the slot already picked) into generic intent classification.
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    existing_patient = make_patient(id_="pat-existing", full_name="Pedro Cassera", dni="30313131")
    patient_gateway = make_patient_gateway(patients=[existing_patient])
    appointment_gateway = make_dentalink_gateway(available_slots=[slot])
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
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
        agreement_gateway=make_agreement_gateway(),
    )
    payload = {"full_name": "cassera", "dni": "30313131", "phone": "+5491122334455"}
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert result["collected_data"]["pending_selected_slot"] == slot
    # Neither the mismatched name nor the DNI it was matched against
    # should survive — the patient was asked to write both again, fresh.
    assert result["collected_data"]["identification_full_name"] is None
    assert result["collected_data"]["identification_dni"] is None


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

    assert "[fake-response for intent=slot_selection_reminder]" in result["response_text"]
    assert "collected_data" not in result
    assert result["response_buttons"] is None
    # Aggregated next-slots screen: one page, no navigation row.
    assert [row.id for row in result["response_list"].rows] == [
        f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
    ]


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

    assert "[fake-response for intent=stale_slot_selection]" in result["response_text"]
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
    assert "[fake-response for intent=propose_reschedule_confirmation]" in result["response_text"]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "SENSITIVE_CONFIRMATION"


@pytest.mark.asyncio
async def test_confirmation_stage_reminds_instead_of_advancing_on_free_text():
    # A genuinely live, resolvable proposal (`pa-1` is actually saved below)
    # plus ambiguous free text with no classified operation: the reminder is
    # still the right response here — only a missing/unresolvable pending
    # action or a clearly different operation should ever skip it (see the
    # dangling/operation-switch tests right below).
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="pending"))
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="si dale",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "collected_data" not in result
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action_type",
    [
        CREATE_APPOINTMENT_ACTION,
        CREATE_PATIENT_ACTION,
        RESCHEDULE_APPOINTMENT_ACTION,
        CANCEL_APPOINTMENT_ACTION,
    ],
)
@pytest.mark.parametrize(
    "user_message,operation_mention",
    [
        ("sí, confirmo el turno", "create"),
        ("qué turno tengo", "view"),
        ("quiero reprogramar", "reschedule"),
        ("quiero cancelar mi turno", "cancel"),
    ],
)
async def test_confirmation_stage_live_proposal_is_never_abandoned_by_free_text(
    user_message, operation_mention, action_type
):
    # T8 (product decision, option A, 2026-09-24: user chose option A after
    # review-33bb80b5a933c040): a REAL pending proposal awaiting
    # confirmation is never abandoned by free text any more, whatever
    # operation it mentions — it always gets the Confirmar/Cancelar
    # reminder back, and the proposal itself stays untouched (`pending`) in
    # the DB. This replaces the old operation-switch/reject behavior
    # (T2/T2b/T4/T5/T7) entirely: only a missing/dangling/expired proposal
    # still routes fresh (see the dangling/expired/no-id tests below,
    # unchanged), and only the existing free-text decline
    # (`_is_free_text_decline`, covered elsewhere) still rejects a live one.
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(
            make_pending_action(id_="pa-1", status="pending", action_type=action_type)
        )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message=user_message,
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation_mention": operation_mention,
        },
    )

    result = await node(state)

    assert "collected_data" not in result
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }
    async with repositories_provider() as repositories:
        untouched = await repositories.pending_actions.get_by_id("pa-1")
        assert untouched is not None
        assert untouched.status == "pending"


@pytest.mark.asyncio
async def test_confirmation_stage_with_a_dangling_pending_action_routes_a_fresh_create_request():
    # Seen live (screenshot, 2026-09-23): a stale STAGE_AWAITING_CONFIRMATION
    # survived from an earlier incarnation of this conversation id, with a
    # `pending_action_id` that no longer resolves to anything real
    # ("dangling" — never saved here, exactly like the screenshot's
    # checkpoint). "Quería agendar un turno" used to get the confirm/cancel
    # reminder forever, because the gate fired on ANY free text regardless
    # of whether there was still a real proposal to remind about. A clearly
    # classified request must win instead — same result as tapping
    # OPERATION_CREATE: straight to the specialty list.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Quería agendar un turno",
        button_payload=None,
        pending_action_id="pa-dangling",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "operation_mention": "create",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert [b.id for b in result["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert "- " not in result["response_text"]
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_with_no_pending_action_id_routes_a_fresh_request():
    # Same as the dangling-id case above, but there was never any
    # `pending_action_id` at all (e.g. a rotated workflow session that
    # expired it outright) — must not be treated as "nothing to route by"
    # and fall into the reminder either.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Quería agendar un turno",
        button_payload=None,
        pending_action_id=None,
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION, "operation_mention": "create"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert [b.id for b in result["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert "- " not in result["response_text"]
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_dangling_action_no_operation_falls_back_to_menu():
    # No usable pending action AND no classified operation either (pure
    # chatter) — still must not remind about a proposal that doesn't exist;
    # falls back to the same operation menu a main-menu reset already uses
    # (same distinct-message regression the button-tap version already
    # guards, see `test_main_menu_button_mid_stage_resets_and_shows_a_
    # distinct_message` — an exploding LLM forces the static fallback text
    # so this asserts the deterministic wording, not the fake's own reply).
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLMProvider(FakeLLMProvider):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    node, _, _ = await _make_node_and_conversation(llm_provider=_ExplodingLLMProvider())
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="si dale",
        button_payload=None,
        pending_action_id="pa-dangling",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["response_text"] == _MAIN_MENU_RESET_MESSAGE
    assert result["collected_data"] == {"stage": STAGE_AWAITING_OPERATION_SELECTION}
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_bare_cancelar_stays_a_reminder_not_a_cancel_operation():
    # "cancelar" alone during CREATE's own confirmation must never be
    # reread as the cancel-APPOINTMENT operation — that would silently
    # abandon a live proposal instead of just declining it. Confirmar/
    # Cancelar are this stage's own buttons: only an explicit decline
    # phrase (`_is_free_text_decline`, covered elsewhere) or the Cancelar
    # button itself may drop the proposal; a bare operation mention of
    # "cancel" here stays exactly as ambiguous as before this change.
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="pending"))
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="cancelar",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "operation_mention": "cancel",
        },
    )

    result = await node(state)

    assert "collected_data" not in result
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_confirmation_stage_confirm_tap_with_no_pending_action_id_routes_a_fresh_request():
    # T2b (review-c980054b8c626f90, R3-button-tap-without-pending-id-
    # reminds): a real Confirmar TAP that somehow arrives with no
    # `pending_action_id` at all must recover into a clean state — not
    # fall through into the generic "unrecognized button" reminder and
    # loop the same Confirmar/Cancelar buttons back at the patient forever
    # (the tap itself can never make a `pending_action_id` reappear). A raw
    # button tap carries no free-text operation mention to route by (unlike
    # the dangling/expired-id tests above, which are free text), so this
    # lands on the same operation menu a main-menu reset already uses —
    # same distinct message as `test_confirmation_stage_dangling_action_
    # no_operation_falls_back_to_menu`.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        pending_action_id=None,
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["response_text"] == "[fake-response for intent=operation_menu]"
    assert result["collected_data"] == {"stage": STAGE_AWAITING_OPERATION_SELECTION}
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_cancelar_tap_with_no_pending_action_id_routes_a_fresh_request():
    # Same as above, mirrored for the Cancelar button.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=REJECT_APPOINTMENT_PAYLOAD,
        pending_action_id=None,
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
    )

    result = await node(state)

    assert result["response_text"] == "[fake-response for intent=operation_menu]"
    assert result["collected_data"] == {"stage": STAGE_AWAITING_OPERATION_SELECTION}
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_free_text_decline_with_no_pending_id_routes_a_fresh_request():
    # Same recovery, but via free text ("no quiero") instead of a button —
    # covered explicitly per the T2b review, alongside the two button-tap
    # cases above, so all three input shapes are proven consistent.
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="no quiero",
        button_payload=None,
        pending_action_id=None,
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION, "operation_mention": "create"},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert [b.id for b in result["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert "- " not in result["response_text"]
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_expired_pending_action_row_routes_a_fresh_request():
    # T2b R3-expired-row-branch-untested: unlike a fully dangling id (never
    # saved at all, covered above), this is exactly what T1's own
    # workflow-session rotation leaves behind — a real row that DOES exist
    # but is no longer `pending`. Must be treated exactly like dangling:
    # not usable to remind about.
    repositories_provider = make_proposal_repositories_provider()
    node, _, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    async with repositories_provider() as repositories:
        await repositories.pending_actions.save(make_pending_action(id_="pa-1", status="expired"))
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Quería agendar un turno",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "operation_mention": "create",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert [b.id for b in result["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]
    assert "- " not in result["response_text"]
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_falls_back_to_reminder_when_pending_action_lookup_fails(
    caplog: pytest.LogCaptureFixture,
):
    # T2b R3-new-db-lookup-unguarded: the repository lookup this gate added
    # in T2 can itself raise (DB blip). Fail safe — fall back to the SAME
    # reminder this gate always gave before T2 added the lookup at all,
    # instead of guessing the proposal is gone and silently dropping
    # possibly-live state; log it per the project's own convention (see
    # `_staffed_specialty_ids_safe`).
    class _ExplodingPendingActionRepository(FakePendingActionRepository):
        async def get_by_id(self, pending_action_id: str):
            raise RuntimeError("db unavailable")

    repositories_provider = make_proposal_repositories_provider(
        pending_actions=_ExplodingPendingActionRepository()
    )
    node, _, _ = await _make_node_and_conversation(
        proposal_repositories_provider=repositories_provider
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="si dale",
        button_payload=None,
        pending_action_id="pa-1",
        collected_data={
            "stage": STAGE_AWAITING_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )

    with caplog.at_level(logging.WARNING, logger="app.agent.nodes.appointment"):
        result = await node(state)

    assert "collected_data" not in result
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }
    assert any("pending action lookup failed" in record.message for record in caplog.records)


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
    assert result["response_text"] == "[fake-response for intent=proposal_rejected]"
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

    # `post_action_context` opens `resolve_interaction.py`'s post-booking
    # closing window (see that module's `POST_ACTION_CLOSE_INTENT`) — the
    # only key left once a create/reschedule/cancel confirmation succeeds.
    assert result["collected_data"] == {"post_action_context": CREATE_APPOINTMENT_ACTION}
    assert result["pending_action_id"] is None
    assert "[fake-response for intent=create_success]" in result["response_text"]
    # Regression: the date used to render in English (`strftime('%A')` is
    # locale-dependent) — the clock emoji is only present via the new
    # `format_confirmation_datetime` helper, so its presence here proves
    # that path is in use.
    assert "🕐" in result["response_text"]
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

    assert "[fake-response for intent=slot_taken]" in result["response_text"]
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

    assert "[fake-response for intent=proposal_expired]" in result["response_text"]
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
    # Regression, seen live: a cancel-selection screen used to reuse the
    # same generic "choose_appointment" intent as reschedule/view, which
    # let the model default to booking-toned phrasing ("te lo reservo y
    # listo") while the patient was cancelling.
    assert "[fake-response for intent=choose_appointment_to_cancel]" in result["response_text"]


@pytest.mark.asyncio
async def test_identification_stage_offers_appointments_for_reschedule_with_distinct_framing():
    slot = _future_slot()
    node, _, appointment_gateway = await _make_node_and_conversation(available_slots=[slot])
    await appointment_gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=slot, idempotency_key="seed-1"
    )
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="Juan Perez, 30123456",
        collected_data={
            "stage": STAGE_AWAITING_IDENTIFICATION,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert "[fake-response for intent=choose_appointment_to_reschedule]" in result["response_text"]


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

    assert result["collected_data"] == {"patient": _PATIENT_PRIMITIVES}
    assert result["response_text"] == "[fake-response for intent=no_appointments]"
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_no_appointments_keeps_identity_and_clears_the_stale_operation_stage():
    node, _, _ = await _make_node_and_conversation()

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

    kept = result["collected_data"]
    assert kept["patient"]["full_name"] == "Juan Perez"
    assert kept["patient"]["dni"] == "30123456"
    assert "stage" not in kept
    assert "operation" not in kept


@pytest.mark.asyncio
async def test_first_visit_intake_is_prefilled_from_the_identified_patient():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Puedo sacar uno ?",
            collected_data={
                "patient": _PATIENT_PRIMITIVES,
                "operation_mention": "create",
            },
        )
    )

    intake = (await _confirm_first_visit(node, result))["collected_data"]["first_visit_intake"]
    assert intake["details"]["full_name"] == "Juan Perez"
    assert intake["details"]["dni"] == "30123456"
    assert intake["ask_fields"] == ["email", "obra_social", "plan"]


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

    assert "[fake-response for intent=appointment_selection_reminder]" in result["response_text"]
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

    assert "[fake-response for intent=stale_appointment_selection]" in result["response_text"]
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
    assert "[fake-response for intent=propose_cancel_confirmation]" in result["response_text"]
    # The patient's name (already known from identification) reaches the
    # LLM call so it can ask for confirmation by name, per this session's
    # brief ("Bárbaro, {nombre} confirmá el turno a cancelar...").
    assert "Juan Perez" in result["response_text"]
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

    assert result["collected_data"] == {"post_action_context": CANCEL_APPOINTMENT_ACTION}
    assert result["pending_action_id"] is None
    assert result["response_text"] == "[fake-response for intent=cancel_success]"
    cancelled = appointment_gateway.get_appointment(str(appointment.id))
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_confirmation_stage_thanks_the_patient_by_name_on_cancel_success():
    # Per this session's brief: after a confirmed cancellation, the patient
    # should be thanked by name and told they can reach administración with
    # any doubts — the LLM writes the actual wording, but the name and the
    # administración mention must reach its context.
    slot = _future_slot()
    repositories_provider = make_proposal_repositories_provider()
    node, _, appointment_gateway = await _make_node_and_conversation(
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
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION, "patient": _PATIENT_PRIMITIVES},
    )

    result = await node(state)

    assert "[fake-response for intent=cancel_success]" in result["response_text"]
    assert "Juan Perez" in result["response_text"]


@pytest.mark.asyncio
async def test_appointment_selection_stage_asks_to_keep_or_change_professional_for_reschedule():
    # Regression: reschedule used to search availability across every
    # professional in the clinic (seen live offering a completely
    # different specialty) — now the patient is asked first.
    old_slot = _future_slot(id_="slot-old", professional_id="prof-1")
    node, conversation_repository, appointment_gateway = await _make_node_and_conversation()
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
            "professional_names": {"prof-1": "Jonathan Kafruni El Khoury"},
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE
    assert result["collected_data"]["rescheduling_appointment_id"] == str(appointment.id)
    assert result["collected_data"]["rescheduling_professional_id"] == "prof-1"
    assert "Jonathan Kafruni El Khoury" in result["response_text"]
    button_ids = [b.id for b in result["response_buttons"]]
    assert RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD in button_ids
    assert RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD in button_ids
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_reschedule_professional_choice_keeps_same_professional_searches_only_them():
    same_professional_slot = _future_slot(id_="slot-new", days=2, professional_id="prof-1")
    other_professional_slot = _future_slot(id_="slot-other", days=2, professional_id="prof-2")
    node, conversation_repository, _ = await _make_node_and_conversation(
        available_slots=[same_professional_slot, other_professional_slot],
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="cleaning"),
        ],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE,
            "patient": _PATIENT_PRIMITIVES,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
            "rescheduling_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_professional_id"] == "prof-1"
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES
    assert result["collected_data"]["available_slots"] == [same_professional_slot]
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


@pytest.mark.asyncio
async def test_reschedule_professional_choice_changing_offers_other_professionals():
    node, _, _ = await _make_node_and_conversation(
        professionals=[
            make_professional(id_="prof-1", specialty_id="cleaning"),
            make_professional(id_="prof-2", specialty_id="cleaning"),
        ],
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE,
            "patient": _PATIENT_PRIMITIVES,
            "operation": RESCHEDULE_APPOINTMENT_ACTION,
            "rescheduling_appointment_id": "appt-1",
            "rescheduling_professional_id": "prof-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PROFESSIONAL_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "cleaning"
    assert [p.id for p in result["collected_data"]["professional_options"]] == [
        "prof-1",
        "prof-2",
    ]
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES


@pytest.mark.asyncio
async def test_slot_selection_stage_proposes_reschedule_when_rescheduling():
    new_slot = _future_slot(id_="slot-new")
    node, conversation_repository, _ = await _make_node_and_conversation(available_slots=[new_slot])
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
    assert "[fake-response for intent=propose_reschedule_confirmation]" in result["response_text"]
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

    assert result["collected_data"] == {"post_action_context": RESCHEDULE_APPOINTMENT_ACTION}
    assert result["pending_action_id"] is None
    assert "[fake-response for intent=reschedule_success]" in result["response_text"]
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

    assert "[fake-response for intent=slot_taken]" in result["response_text"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    unchanged = appointment_gateway.get_appointment(str(appointment.id))
    assert unchanged is not None
    assert unchanged.slot == old_slot
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.input_state == "INTERACTIVE_SELECTION"


# --- Flow-based identification (verification + registration Flows) -------


@pytest.mark.asyncio
async def test_begin_identification_sends_the_verification_flow_when_configured():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot], verification_flow_id="flow-verify"
    )
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_FLOW
    assert result["response_flow"].flow_id == "flow-verify"
    assert result["response_flow"].flow_token == "conv-1"
    assert result["response_text"]


@pytest.mark.asyncio
async def test_begin_identification_falls_back_to_text_when_no_flow_configured():
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
    assert "response_flow" not in result


@pytest.mark.asyncio
async def test_verification_flow_response_for_a_known_patient_asks_to_confirm():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot],
        patients=[make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")],
        verification_flow_id="flow-verify",
        registration_flow_id="flow-register",
    )
    payload = f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Juan Perez", "dni": "30123456"}}'
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=payload,
        collected_data={
            "stage": STAGE_AWAITING_VERIFICATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_CONFIRMATION
    assert result["collected_data"]["patient"]["full_name"] == "Juan Perez"
    assert "Juan Perez" in result["response_text"]
    assert {b.id for b in result["response_buttons"]} == {
        CONFIRM_APPOINTMENT_PAYLOAD,
        REJECT_APPOINTMENT_PAYLOAD,
    }


@pytest.mark.asyncio
async def test_verification_flow_response_for_an_unknown_patient_sends_registration_flow():
    node, _, _ = await _make_node_and_conversation(
        patients=[], verification_flow_id="flow-verify", registration_flow_id="flow-register"
    )
    payload = (
        f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Nadie Registrado", "dni": "30999999"}}'
    )
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=payload,
        collected_data={"stage": STAGE_AWAITING_VERIFICATION_FLOW},
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_REGISTRATION_FLOW
    assert result["response_flow"].flow_id == "flow-register"


@pytest.mark.asyncio
async def test_verification_flow_stage_reminds_when_the_reply_is_not_a_flow_response():
    node, _, _ = await _make_node_and_conversation(verification_flow_id="flow-verify")
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="hola",
        collected_data={"stage": STAGE_AWAITING_VERIFICATION_FLOW},
    )

    result = await node(state)

    assert result["response_text"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_verification_confirmation_accepted_continues_to_slot_proposal():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_VERIFICATION_CONFIRMATION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
            "patient": _PATIENT_PRIMITIVES,
            "verified_patient_id": "pat-1",
        },
    )

    result = await node(state)

    assert result["pending_action_id"]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION


@pytest.mark.asyncio
async def test_verification_confirmation_rejected_sends_registration_flow():
    node, _, _ = await _make_node_and_conversation(registration_flow_id="flow-register")
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=REJECT_APPOINTMENT_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_VERIFICATION_CONFIRMATION,
            "patient": _PATIENT_PRIMITIVES,
            "verified_patient_id": "pat-1",
        },
    )

    result = await node(state)

    assert result["collected_data"]["stage"] == STAGE_AWAITING_REGISTRATION_FLOW
    assert result["response_flow"].flow_id == "flow-register"


@pytest.mark.asyncio
async def test_registration_flow_creates_the_patient_with_email_and_links_the_matched_agreement():
    slot = _future_slot()
    osde = make_agreement(id_="agr-1", name="OSDE")
    node, _, appointment_gateway = await _make_node_and_conversation(
        available_slots=[slot],
        patients=[],
        agreements=[osde],
        conversation_id="ycloud-+5491122334455",
    )
    payload = (
        f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456", '
        f'"email": "rosa@example.com", "obra_social": "OSDE"}}'
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=payload,
        collected_data={
            "stage": STAGE_AWAITING_REGISTRATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["patient"]["full_name"] == "Rosa Gomez"
    assert "collected_data" in result


@pytest.mark.asyncio
async def test_registration_flow_ignores_an_unmatched_agreement_name():
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot],
        patients=[],
        agreements=[],
        conversation_id="ycloud-+5491122334455",
    )
    payload = (
        f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456", '
        f'"obra_social": "Alguna Cobertura Inexistente"}}'
    )
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=payload,
        collected_data={
            "stage": STAGE_AWAITING_REGISTRATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["patient"]["full_name"] == "Rosa Gomez"


@pytest.mark.asyncio
async def test_registration_flow_recovers_from_a_create_patient_race():
    slot = _future_slot()
    existing_patient = make_patient(id_="pat-existing", full_name="Rosa Gomez", dni="30123456")
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot],
        patients=[existing_patient],
        conversation_id="ycloud-+5491122334455",
    )
    payload = f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456"}}'
    state = make_agent_state(
        conversation_id="ycloud-+5491122334455",
        button_payload=payload,
        collected_data={
            "stage": STAGE_AWAITING_REGISTRATION_FLOW,
            "operation": CREATE_APPOINTMENT_ACTION,
            "pending_selected_slot": slot,
        },
    )

    result = await node(state)

    assert result["collected_data"]["patient"]["id"] == "pat-existing"


@pytest.mark.asyncio
async def test_registration_flow_reminds_when_the_reply_is_not_a_flow_response():
    node, _, _ = await _make_node_and_conversation(registration_flow_id="flow-register")
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="hola",
        collected_data={"stage": STAGE_AWAITING_REGISTRATION_FLOW},
    )

    result = await node(state)

    assert result["response_text"]
    assert "collected_data" not in result


# --- PR 2: create-selection subgraph delegation ---------------------------


def test_should_use_appointment_decision_subgraph_covers_the_first_slice_create_stages():
    for stage in (
        STAGE_AWAITING_SPECIALTY_SELECTION,
        STAGE_AWAITING_PROFESSIONAL_SELECTION,
        STAGE_AWAITING_SLOT_SELECTION,
    ):
        assert should_use_appointment_decision_subgraph(stage, {}) is True


def test_should_use_appointment_decision_subgraph_excludes_no_availability_and_no_slots_follow_up():
    # First-slice migration only owns specialty/professional/slot selection —
    # the no-availability/no-slot follow-up choice handlers stay legacy-owned.
    assert (
        should_use_appointment_decision_subgraph(STAGE_AWAITING_NO_AVAILABILITY_CHOICE, {}) is False
    )
    assert should_use_appointment_decision_subgraph(STAGE_AWAITING_NO_SLOTS_CHOICE, {}) is False


def test_should_use_appointment_decision_subgraph_excludes_reschedule_markers():
    # RESCHEDULE identifies the patient up front and proposes immediately on
    # a valid slot — a different contract than this first slice's
    # pre-identification `pending_selected_slot` handoff, so it never
    # delegates even though it shares `STAGE_AWAITING_SLOT_SELECTION`.
    assert (
        should_use_appointment_decision_subgraph(
            STAGE_AWAITING_SLOT_SELECTION, {"rescheduling_appointment_id": "appt-1"}
        )
        is False
    )


def test_should_use_appointment_decision_subgraph_requires_create_operation_with_no_stage():
    assert (
        should_use_appointment_decision_subgraph(None, {"operation": CREATE_APPOINTMENT_ACTION})
        is True
    )
    for operation in (RESCHEDULE_APPOINTMENT_ACTION, CANCEL_APPOINTMENT_ACTION, None):
        assert should_use_appointment_decision_subgraph(None, {"operation": operation}) is False


@pytest.mark.asyncio
async def test_decision_node_attribution_never_replaces_the_public_stage_cursor():
    # Internal subgraph node names (`choose_specialty`, `choose_professional`,
    # ...) are observability-only — the public checkpoint cursor must always
    # stay one of the legacy stage strings.
    node, _, _ = await _make_node_and_conversation(
        specialties=[make_specialty(id_="cleaning", name="Ortodoncia")],
        professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
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

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    for internal_name in (
        "choose_specialty",
        "choose_browse_mode",
        "choose_professional",
        "search_availability",
        "search_availability_any_professional",
    ):
        assert result["collected_data"]["stage"] != internal_name


@pytest.mark.asyncio
async def test_reschedule_slot_selection_stays_legacy_owned_end_to_end():
    # Regression for the delegation gate: a reschedule turn reaching
    # `STAGE_AWAITING_SLOT_SELECTION` must still be handled by the legacy
    # FSM branch (identity known already, proposes immediately) rather than
    # the create-only subgraph's `begin_identification` handoff.
    new_slot = _future_slot(id_="slot-new")
    node, _, _ = await _make_node_and_conversation(available_slots=[new_slot])
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
    assert result["pending_action_id"] is not None


@pytest.mark.asyncio
async def test_navigation_target_main_from_idle_matches_the_menu_main_button():
    # T3 (free-text menu-intents parity): "volver al menú principal" with
    # no active flow (idle) must produce the EXACT same response a real
    # MENU_MAIN_PAYLOAD tap does — both now go through the shared
    # `_welcome_reset_response` helper, so this proves they stay identical
    # rather than drifting apart as two separate copies.
    node, _, _ = await _make_node_and_conversation()
    button_state = make_agent_state(
        conversation_id="conv-1",
        button_payload=MENU_MAIN_PAYLOAD,
        collected_data={},
    )
    free_text_state = make_agent_state(
        conversation_id="conv-1",
        user_message="volver al menú principal",
        button_payload=None,
        collected_data={"navigation_target": "main"},
    )

    button_result = await node(button_state)
    free_text_result = await node(free_text_state)

    assert free_text_result == button_result
    assert button_result["response_text"] == WELCOME_TEXT
    assert button_result["response_list"] == WELCOME_LIST
    assert button_result["collected_data"] == {}
    assert button_result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_navigation_target_main_mid_stage_matches_the_menu_main_button():
    # Same parity, mid-flow: a patient stuck picking a specialty who says
    # "volver al menú principal" must land exactly where tapping "Menú
    # principal" mid-flow already does.
    node, _, _ = await _make_node_and_conversation()
    button_state = make_agent_state(
        conversation_id="conv-1",
        button_payload=MENU_MAIN_PAYLOAD,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
        },
    )
    free_text_state = make_agent_state(
        conversation_id="conv-1",
        user_message="volver al menú principal",
        button_payload=None,
        collected_data={
            "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
            "operation": CREATE_APPOINTMENT_ACTION,
            "navigation_target": "main",
        },
    )

    button_result = await node(button_state)
    free_text_result = await node(free_text_state)

    assert free_text_result == button_result
    assert button_result["response_text"] == WELCOME_TEXT
    assert button_result["response_list"] == WELCOME_LIST
    assert button_result["collected_data"] == {}
    assert button_result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_confirmation_stage_cancelar_tap_ignores_a_stale_operation_mention():
    # T9 (review-bae960a902ead91b, R3-001, defense in depth alongside
    # resolve_interaction.py's own per-turn stripping — the single-place fix
    # this finding shares with R3-002/R3-003): a real Cancelar TAP never
    # goes through the LLM's `understand()` call, so it can never itself
    # justify an `operation_mention` — any mention already sitting in
    # `collected_data` at this point can only be a leftover from an
    # earlier, unrelated turn. Before this fix, this stale mention silently
    # routed into a create flow instead of the same clean menu recovery a
    # bare Cancelar tap with nothing to confirm already gives (see
    # `test_confirmation_stage_cancelar_tap_with_no_pending_action_id_
    # routes_a_fresh_request` above).
    node, _, _ = await _make_node_and_conversation()
    state = make_agent_state(
        conversation_id="conv-1",
        button_payload=REJECT_APPOINTMENT_PAYLOAD,
        pending_action_id=None,
        collected_data={"stage": STAGE_AWAITING_CONFIRMATION, "operation_mention": "create"},
    )

    result = await node(state)

    assert result["response_text"] == "[fake-response for intent=operation_menu]"
    assert result["collected_data"] == {"stage": STAGE_AWAITING_OPERATION_SELECTION}
    assert result["pending_action_id"] is None


@pytest.mark.asyncio
async def test_a_stale_navigation_target_does_not_reset_a_later_idle_turn():
    # T9 (review-bae960a902ead91b, R3-002): `navigation_target="main"` set
    # by resolve_interaction while a live proposal intercepted "volver al
    # menú" (T8's own confirmation reminder never clears it — it forwards
    # no `collected_data` update at all) must not survive to reset a LATER,
    # unrelated idle turn once the proposal is resolved and the stage drops
    # back to `None`. The fix lives in resolve_interaction.py (single
    # place, per this task's own design) — a test isolated to appointment.py
    # alone can't prove it, since appointment.py's own idle-navigation
    # branch has no way to tell a stale value from a fresh one; this runs
    # both nodes in sequence, exactly as the real graph does turn to turn.
    from app.agent.nodes.resolve_interaction import create_resolve_interaction_node

    resolve_node = create_resolve_interaction_node(FakeLLMProvider())
    node, _, _ = await _make_node_and_conversation()

    # Simulates the checkpoint left behind by an earlier turn: idle now
    # (the live proposal that intercepted "volver al menú" has since been
    # resolved and the stage dropped), but `navigation_target` from that
    # earlier turn was never cleared.
    stale_collected_data = {"navigation_target": "main"}
    state = make_agent_state(
        conversation_id="conv-1",
        user_message="qué especialidades tienen",
        button_payload=None,
        collected_data=stale_collected_data,
    )

    resolve_result = await resolve_node(state)
    assert resolve_result["intent"] == "specialties"

    next_state = make_agent_state(
        conversation_id="conv-1",
        user_message="qué especialidades tienen",
        button_payload=None,
        # Same replace-only-if-present semantics the real `collected_data`
        # channel uses (AgentState's own docstring): a node that returns no
        # `collected_data` key leaves the PRIOR turn's value untouched.
        collected_data=resolve_result.get("collected_data", stale_collected_data),
    )

    result = await node(next_state)

    assert result.get("response_text") != WELCOME_TEXT


def _slot_selection_state(slot, **overrides):
    """A create flow at the slot list: the slot chosen, nobody identified yet."""
    collected_data = {
        "stage": STAGE_AWAITING_SLOT_SELECTION,
        "chosen_specialty_id": "cleaning",
        "chosen_specialty_name": "Ortodoncia",
        "available_slots": [slot],
        "professional_names": {"prof-1": "Dra. Laura Pérez"},
        "slots_page": 0,
        **overrides.pop("collected_data", {}),
    }
    return make_agent_state(
        conversation_id="conv-1",
        button_payload=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        collected_data=collected_data,
        **overrides,
    )


@pytest.mark.asyncio
async def test_the_picked_slot_and_create_operation_survive_identification():
    # Chat A regression (live, v0.42.3): after picking a slot the patient was asked for
    # name + DNI, and once given the agent answered "no encontramos turnos próximos"
    # (the reschedule/cancel/view path) because the create operation was only implicit
    # in the slot stage and never carried through identification.
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])

    ask = await node(_slot_selection_state(slot))

    assert ask["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert ask["collected_data"]["operation"] == CREATE_APPOINTMENT_ACTION
    assert ask["collected_data"]["pending_selected_slot"] == slot

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Juan Perez 30123456",
            collected_data=ask["collected_data"],
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["pending_selected_slot"] == slot
    assert result["response_buttons"] is not None
    assert result["pending_action_id"] is not None


@pytest.mark.asyncio
async def test_identification_with_a_picked_slot_never_takes_the_no_appointments_path():
    # Same regression from a checkpoint that lost the operation key: a pending slot
    # pick can only mean a booking.
    slot = _future_slot()
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot], llm_provider=llm)

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            user_message="Juan Perez 30123456",
            collected_data={
                "stage": STAGE_AWAITING_IDENTIFICATION,
                "pending_selected_slot": slot,
                "chosen_specialty_id": "cleaning",
                "professional_names": {"prof-1": "Dra. Laura Pérez"},
            },
        )
    )

    assert "no_appointments" not in llm.intents
    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION


@pytest.mark.asyncio
async def test_a_remembered_patient_is_not_asked_for_identification_after_picking_a_slot():
    slot = _future_slot()
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot], llm_provider=llm)

    result = await node(_slot_selection_state(slot, patient_identity=_PATIENT_PRIMITIVES))

    assert "ask_identification" not in llm.intents
    assert result["collected_data"]["stage"] == STAGE_AWAITING_CONFIRMATION
    assert result["collected_data"]["patient"] == _PATIENT_PRIMITIVES
    assert result["pending_action_id"] is not None


@pytest.mark.asyncio
async def test_a_remembered_patient_skips_the_first_visit_question_when_booking_again():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_CREATE_PAYLOAD,
            collected_data={},
            patient_identity=_PATIENT_PRIMITIVES,
        )
    )

    assert "first_visit_question" not in llm.intents
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["response_list"] is not None


@pytest.mark.asyncio
async def test_a_remembered_patient_is_not_asked_for_identification_to_view_appointments():
    llm = _IntakeLLM()
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)

    await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=OPERATION_CANCEL_PAYLOAD,
            collected_data={},
            patient_identity=_PATIENT_PRIMITIVES,
        )
    )

    assert "ask_identification" not in llm.intents
    # Nothing scheduled for this patient in the fake gateway: the no-appointments reply,
    # never an identification prompt.
    assert "no_appointments" in llm.intents


@pytest.mark.asyncio
async def test_identifying_a_patient_reports_the_identity_to_remember():
    node, _, _ = await _make_node_and_conversation()
    question = await _start_create(node)

    result = await _answer_as_existing_patient(node, question)

    assert result["patient_identity"]["dni"] == "30123456"
    assert result["patient_identity"]["full_name"] == "Juan Perez"


@pytest.mark.asyncio
async def test_a_patient_awaiting_verification_confirmation_is_not_remembered_yet():
    node, _, _ = await _make_node_and_conversation()

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=REJECT_APPOINTMENT_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_VERIFICATION_CONFIRMATION,
                "operation": CREATE_APPOINTMENT_ACTION,
                "patient": _PATIENT_PRIMITIVES,
                "verified_patient_id": "pat-1",
            },
        )
    )

    assert result.get("patient_identity") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("via", ["button", "typed"])
async def test_the_main_menu_resets_the_workflow_state_however_it_is_requested(via):
    slot = _future_slot()
    node, _, _ = await _make_node_and_conversation(available_slots=[slot])
    in_flight = {
        "stage": STAGE_AWAITING_CONFIRMATION,
        "operation": CREATE_APPOINTMENT_ACTION,
        "pending_selected_slot": slot,
        "patient": _PATIENT_PRIMITIVES,
        "first_visit_completed": True,
        "first_visit_intake": {"stage": "collect"},
        "chosen_specialty_id": "cleaning",
    }
    request = (
        {"button_payload": MENU_MAIN_PAYLOAD}
        if via == "button"
        else {"user_message": "Menú principal"}
    )

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            collected_data=in_flight,
            pending_action_id="pending-1",
            patient_identity=_PATIENT_PRIMITIVES,
            **request,
        )
    )

    assert result["response_text"] == WELCOME_TEXT
    assert result["response_list"] == WELCOME_LIST
    assert result["collected_data"] == {}
    assert result["pending_action_id"] is None
    # The reset clears the workflow only; the remembered patient stays known.
    # The reset never overwrites the remembered patient (state keeps it untouched).
    assert "patient_identity" not in result


_REPEATED_INTRO = "Buenísimo, gracias por la info. Todavía me faltan estos datos:"


class _RepeatingIntroLLM(_IntakeLLM):
    """The live model, which opened every re-ask with the same sentence."""

    def __init__(self) -> None:
        super().__init__()
        self.ask_contexts = []

    async def generate_response(self, context):
        if context.intent == "first_visit_intake_ask":
            self.intents.append(context.intent)
            self.ask_contexts.append(context)
            # The first ask reads differently; every re-ask then opens the same way.
            return _REPEATED_INTRO if len(self.ask_contexts) > 1 else "Necesito unos datos:"
        return await super().generate_response(context)


async def _two_consecutive_re_asks(llm):
    """Confirm the first visit, then send two replies that each leave fields missing."""
    node, _, _ = await _make_node_and_conversation(llm_provider=llm)
    recent: list[dict[str, str]] = []

    def remember(user_text, result):
        if user_text:
            recent.append({"role": "user", "content": user_text})
        recent.append({"role": "assistant", "content": result["response_text"]})

    result = await _confirm_first_visit(node, await _start_create(node))
    remember("", result)
    replies = []
    for text in ("Soy Ana Pérez", "ana@example.com"):
        result = await node(
            make_agent_state(
                conversation_id="conv-1",
                user_message=text,
                collected_data=result["collected_data"],
                recent_messages=list(recent),
            )
        )
        remember(text, result)
        replies.append(result["response_text"])
    return replies, llm


@pytest.mark.asyncio
async def test_consecutive_re_asks_do_not_repeat_the_intro_even_if_the_llm_does():
    # Chat B regression (live): "Buenísimo, gracias por la info. Todavía me faltan…"
    # opened consecutive re-asks. That sentence came from the LLM (the static fallback
    # reads differently), so the repeat must be caught after generation too.
    (first_re_ask, second_re_ask), _ = await _two_consecutive_re_asks(_RepeatingIntroLLM())

    first_intro = first_re_ask.split("\n\n")[0]
    second_intro = second_re_ask.split("\n\n")[0]
    assert first_intro == _REPEATED_INTRO
    assert second_intro != first_intro
    assert second_re_ask.split("\n\n")[1].startswith("- ")


@pytest.mark.asyncio
async def test_the_intake_ask_tells_the_llm_the_previous_intro_and_asks_for_variety():
    llm = _RepeatingIntroLLM()
    await _two_consecutive_re_asks(llm)

    second_ask = llm.ask_contexts[-1]
    assert second_ask.collected_data["intro_anterior"] == _REPEATED_INTRO
    assert "No repitas" in str(second_ask.collected_data["instruccion"])
    assert second_ask.temperature is not None and second_ask.temperature >= 0.8


@pytest.mark.asyncio
async def test_static_fallback_intros_of_consecutive_re_asks_differ():
    from app.infrastructure.llm.exceptions import LLMTimeoutError

    class _ExplodingLLM(_IntakeLLM):
        async def generate_response(self, context):
            raise LLMTimeoutError("boom")

    (first_re_ask, second_re_ask), _ = await _two_consecutive_re_asks(_ExplodingLLM())

    assert first_re_ask.split("\n\n")[0] != second_re_ask.split("\n\n")[0]


@pytest.mark.asyncio
async def test_no_appointments_reply_offers_administration_with_buttons():
    from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS

    class _OfferingLLM(_IntakeLLM):
        async def generate_response(self, context):
            if context.intent == "no_appointments":
                return "No encontramos turnos. Querés que te comunique con administración?"
            return await super().generate_response(context)

    node, _, _ = await _make_node_and_conversation(llm_provider=_OfferingLLM())

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

    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS
    assert result["collected_data"]["handoff_offer_pending"] is True
    assert result["collected_data"]["patient"]["dni"] == "30123456"


@pytest.mark.asyncio
async def test_a_patient_found_by_the_verification_flow_is_not_remembered_until_confirmed():
    node, _, _ = await _make_node_and_conversation()
    payload = f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Juan Perez", "dni": "30123456"}}'

    result = await node(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=payload,
            collected_data={
                "stage": STAGE_AWAITING_VERIFICATION_FLOW,
                "operation": CREATE_APPOINTMENT_ACTION,
            },
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_VERIFICATION_CONFIRMATION
    assert result["collected_data"]["patient"]["dni"] == "30123456"
    assert "patient_identity" not in result


async def _confirm_create_patient(agreement_gateway=None, existing=False):
    repositories_provider = make_proposal_repositories_provider()
    conversation_repository = make_conversation_repository()
    agreement_gateway = agreement_gateway or _recording_gateway()
    patients = [_EXISTING_PATIENT_FACTORY("Maria Soto", "30111222")] if existing else []
    await conversation_repository.save(make_conversation(id_="ycloud-+5491122334455", mode="agent"))
    node = create_appointment_node(
        appointment_gateway=make_dentalink_gateway(),
        patient_gateway=make_patient_gateway(patients=patients),
        proposal_repositories_provider=repositories_provider,
        conversation_repository=conversation_repository,
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        llm_provider=FakeLLMProvider(),
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="cleaning", name="Ortodoncia")]
        ),
        agreement_gateway=agreement_gateway,
    )
    payload = {
        "full_name": "Maria Soto",
        "dni": "30111222",
        "phone": "+5491122334455",
        "obra_social": "OSDE",
        "email": "maria@gmail.com",
    }
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
    return await node(
        make_agent_state(
            conversation_id="ycloud-+5491122334455",
            button_payload=CONFIRM_APPOINTMENT_PAYLOAD,
            pending_action_id="pa-1",
            collected_data={"stage": STAGE_AWAITING_CONFIRMATION},
        )
    )


@pytest.mark.asyncio
async def test_confirmed_new_patient_already_linked_agreement_tells_the_patient_and_continues():
    success = await _confirm_create_patient()

    result = await _confirm_create_patient(
        _recording_gateway(link=AsyncMock(side_effect=AgreementAlreadyLinkedError("pat-1", "osde")))
    )

    _assert_notice_then_same_next_step(result, success)


async def _submit_registration_flow(agreement_gateway=None, existing=False):
    slot = _future_slot()
    patients = [_EXISTING_PATIENT_FACTORY("Rosa Gomez", "30123456")] if existing else []
    node, _, _ = await _make_node_and_conversation(
        available_slots=[slot],
        patients=patients,
        patient_gateway=make_patient_gateway(patients=patients),
        agreement_gateway=agreement_gateway or _recording_gateway(),
        conversation_id="ycloud-+5491122334455",
    )
    payload = (
        f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456", '
        f'"email": "rosa@example.com", "obra_social": "OSDE"}}'
    )
    return await node(
        make_agent_state(
            conversation_id="ycloud-+5491122334455",
            button_payload=payload,
            collected_data={
                "stage": STAGE_AWAITING_REGISTRATION_FLOW,
                "operation": CREATE_APPOINTMENT_ACTION,
                "pending_selected_slot": slot,
            },
        )
    )


@pytest.mark.asyncio
async def test_registration_flow_already_linked_agreement_tells_the_patient_and_continues():
    success = await _submit_registration_flow()

    result = await _submit_registration_flow(
        _recording_gateway(link=AsyncMock(side_effect=AgreementAlreadyLinkedError("pat-1", "osde")))
    )

    _assert_notice_then_same_next_step(result, success)


_SITE_RUNNERS = [
    pytest.param(_first_visit_confirm_with_link, id="first-visit"),
    pytest.param(_confirm_create_patient, id="confirm-create-patient"),
    pytest.param(_submit_registration_flow, id="registration-flow"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("run", _SITE_RUNNERS)
@pytest.mark.parametrize(
    ("held", "expect_link", "notice"),
    [
        ([_OSDE], False, _NOTICE_ON_RECORD),
        ([], True, _NOTICE_LINKED_NOW),
        ([_OTHER], False, _NOTICE_ON_RECORD),
    ],
    ids=["same-agreement", "no-agreement", "different-agreement"],
)
async def test_an_existing_patient_is_never_overwritten_and_gets_the_matching_notice(
    run, held, expect_link, notice
):
    success = await run()
    gateway = _recording_gateway(patient_agreements={_EXISTING_ID: list(held)} if held else None)

    result = await run(gateway, existing=True)

    assert gateway.link_calls == ([(_EXISTING_ID, "osde")] if expect_link else [])
    assert result["response_text"] == f"{notice}\n\n{success['response_text']}"
    assert result["response_buttons"] == success["response_buttons"]
    assert result.get("response_list") == success.get("response_list")
    assert result["collected_data"].get("stage") == success["collected_data"].get("stage")
    lowered = result["response_text"].casefold()
    assert not any(word in lowered for word in _NO_ERROR_WORDS)
    assert await gateway.get_patient_agreements(_EXISTING_ID) == (
        [_OSDE] if expect_link else list(held)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("run", _SITE_RUNNERS)
async def test_a_newly_created_patient_still_gets_the_agreement_linked(run):
    gateway = _recording_gateway()

    result = await run(gateway)

    assert len(gateway.link_calls) == 1
    assert gateway.link_calls[0][1] == "osde"
    assert "Ya figurás" not in result["response_text"]


@pytest.mark.asyncio
async def test_first_visit_failing_agreement_lookup_for_an_existing_patient_does_not_link():
    gateway = _recording_gateway(get_error=RuntimeError("down"))

    result = await _first_visit_confirm_with_link(gateway, existing=True)

    assert gateway.link_calls == []
    assert "El alta quedó pendiente" in result["response_text"]
    assert {button.title for button in result["response_buttons"]} == {
        "✅ Reintentar",
        "✏️ Modificar",
        "❌ Cancelar",
    }
