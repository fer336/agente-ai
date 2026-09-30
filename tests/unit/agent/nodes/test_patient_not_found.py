"""Audit v0.44.0: an unknown patient was asked for insurance and email as if identified."""

import pytest

from app.agent.first_visit_intake_subgraph import (
    FIRST_VISIT_CANCEL_PAYLOAD,
    INTAKE_FIELD_LABELS,
)
from app.agent.nodes.appointment import (
    _PATIENT_NOT_FOUND_MESSAGE,
    CANCEL_APPOINTMENT_ACTION,
    CREATE_APPOINTMENT_ACTION,
    OPERATION_CREATE_PAYLOAD,
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_OPERATION_SELECTION,
    STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import ResponseContext
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    PATIENT_NOT_FOUND_REGISTER_PAYLOAD,
    PATIENT_NOT_FOUND_RETRY_PAYLOAD,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation

_UNKNOWN = "Rosa Gomez, 30999888"
_NOT_FOUND_REPLY = "No encontré ningún paciente con esos datos. ¿Qué querés hacer?"


class _ScriptedLLM(FakeLLMProvider):
    def __init__(self, not_found_reply: str | None = None) -> None:
        super().__init__()
        self._reply = not_found_reply
        self.contexts: list[ResponseContext] = []

    async def generate_response(self, context: ResponseContext) -> str:
        self.contexts.append(context)
        if context.intent == "patient_not_found" and self._reply is not None:
            return self._reply
        return await super().generate_response(context)


async def _not_found_after_existing_patient_answer(node, conversation_id="conv-1"):
    """The audit path: create -> "ya soy paciente" -> name + DNI Dentalink does not know."""
    question = await node(
        make_agent_state(
            conversation_id=conversation_id,
            button_payload=OPERATION_CREATE_PAYLOAD,
            collected_data={"stage": STAGE_AWAITING_OPERATION_SELECTION},
        )
    )
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
            user_message=_UNKNOWN,
            collected_data=ask["collected_data"],
        )
    )


@pytest.mark.asyncio
async def test_audit_replay_says_no_patient_was_found_and_offers_three_ways_forward():
    node, _, _ = await make_node_and_conversation(llm_provider=_ScriptedLLM(_NOT_FOUND_REPLY))

    result = await _not_found_after_existing_patient_answer(node)

    text = result["response_text"].casefold()
    assert "obra social" not in text
    assert "mail" not in text
    assert "osde" not in text
    assert "no encontr" in text
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (PATIENT_NOT_FOUND_REGISTER_PAYLOAD, "🆕 Registrarme"),
        (PATIENT_NOT_FOUND_RETRY_PAYLOAD, "🔁 Probar otro dato"),
        (MENU_ADMIN_PAYLOAD, "💬 Asesor"),
    ]
    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_the_unknown_patient_is_never_treated_as_identified():
    node, _, _ = await make_node_and_conversation()

    result = await _not_found_after_existing_patient_answer(node)

    data = result["collected_data"]
    assert "patient" not in data
    assert "first_visit_completed" not in data
    assert result.get("pending_action_id") is None
    assert result.get("response_list") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [CREATE_APPOINTMENT_ACTION, CANCEL_APPOINTMENT_ACTION])
async def test_the_same_choice_is_offered_from_a_direct_identification_stage(operation):
    node, _, _ = await make_node_and_conversation(patients=[])

    result = await node(
        make_agent_state(
            user_message=_UNKNOWN,
            collected_data={"stage": STAGE_AWAITING_IDENTIFICATION, "operation": operation},
        )
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_the_wording_is_llm_built_without_the_names_and_never_asks_for_insurance():
    llm = _ScriptedLLM(_NOT_FOUND_REPLY)
    node, _, _ = await make_node_and_conversation(llm_provider=llm)

    result = await _not_found_after_existing_patient_answer(node)

    assert result["response_text"] == _NOT_FOUND_REPLY
    context = next(c for c in llm.contexts if c.intent == "patient_not_found")
    assert "30999888" not in str(context.collected_data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "No te encontré. Pasame tu obra social y tu mail para crear la ficha.",
        "Hola! No encontré tu ficha, decime tu correo.",
        "Listo, ya te lo cancelé. No encontré el paciente.",
    ],
)
async def test_a_reply_that_asks_for_insurance_or_claims_an_action_gets_the_static_wording(reply):
    node, _, _ = await make_node_and_conversation(llm_provider=_ScriptedLLM(reply))

    result = await _not_found_after_existing_patient_answer(node)

    assert result["response_text"] == _PATIENT_NOT_FOUND_MESSAGE


async def _tap(node, result, payload, **overrides):
    return await node(
        make_agent_state(
            button_payload=payload, collected_data=result["collected_data"], **overrides
        )
    )


@pytest.mark.asyncio
async def test_registering_starts_the_five_field_intake_with_name_and_dni_prefilled():
    node, _, _ = await make_node_and_conversation()
    not_found = await _not_found_after_existing_patient_answer(node)

    result = await _tap(node, not_found, PATIENT_NOT_FOUND_REGISTER_PAYLOAD)

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert data["first_visit_intake"]["stage"] == "collect"
    assert data["first_visit_intake"]["details"] == {"full_name": "Rosa Gomez", "dni": "30999888"}
    assert data["identification_full_name"] == "Rosa Gomez"
    assert data["identification_dni"] == "30999888"
    text = result["response_text"]
    assert INTAKE_FIELD_LABELS["email"] in text
    assert INTAKE_FIELD_LABELS["obra_social"] in text
    assert INTAKE_FIELD_LABELS["plan"] in text
    assert f"- {INTAKE_FIELD_LABELS['full_name']}" not in text
    assert f"- {INTAKE_FIELD_LABELS['dni']}" not in text


@pytest.mark.asyncio
async def test_trying_other_data_asks_for_name_and_dni_again_and_finds_the_corrected_patient():
    node, _, _ = await make_node_and_conversation()
    not_found = await _not_found_after_existing_patient_answer(node)

    retry = await _tap(node, not_found, PATIENT_NOT_FOUND_RETRY_PAYLOAD)

    assert retry["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert "ask_identification" in retry["response_text"]
    assert retry["response_buttons"] is None

    found = await node(
        make_agent_state(
            user_message="Juan Perez, 30123456", collected_data=retry["collected_data"]
        )
    )

    assert found["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert found["collected_data"]["patient"]["dni"] == "30123456"


@pytest.mark.asyncio
async def test_free_text_at_the_choice_only_repeats_the_three_buttons():
    node, _, _ = await make_node_and_conversation()
    not_found = await _not_found_after_existing_patient_answer(node)

    result = await node(
        make_agent_state(user_message="no sé", collected_data=not_found["collected_data"])
    )

    assert result["response_buttons"] == not_found["response_buttons"]
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_the_advisor_button_routes_to_the_handoff_even_mid_choice():
    resolve = create_resolve_interaction_node(FakeLLMProvider())

    result = await resolve(
        make_agent_state(
            user_message="💬 Asesor",
            button_payload=MENU_ADMIN_PAYLOAD,
            collected_data={"stage": STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE},
        )
    )

    assert result["intent"] == "handoff"
