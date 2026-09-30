"""A data answer during a data-collection stage stays in that stage (audit follow-up Q2)."""

import pytest

from app.agent.nodes.appointment import (
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE,
)
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import ExtractionResult
from app.domain.value_objects.menu_payloads import PATIENT_NOT_FOUND_RETRY_PAYLOAD
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation

_INTAKE = {
    "stage": STAGE_AWAITING_FIRST_VISIT_INTAKE,
    "first_visit_intake": {
        "stage": "collect",
        "details": {"full_name": "Rosa Gomez", "dni": "30999888", "email": "rosa@example.com"},
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["OSDE 210", "osde", "210", "Swiss Medical", "Galeno."])
@pytest.mark.parametrize(
    "stage", [STAGE_AWAITING_FIRST_VISIT_INTAKE, STAGE_AWAITING_IDENTIFICATION]
)
async def test_a_data_answer_is_never_routed_to_an_information_node(answer, stage):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=answer, collected_data={"stage": stage}))

    assert result["intent"] == "appointment"
    assert result.get("interruption") is None


@pytest.mark.asyncio
async def test_a_real_question_mid_intake_still_reaches_the_information_node():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="¿atienden por OSDE?", collected_data=_INTAKE)
    )

    assert result["intent"] == "insurance"
    assert result["interruption"] == "temporary"
    # Nothing is rewritten: the intake stage and its details stay as they were.
    assert "collected_data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "intent"),
    [("Voy a llegar tarde", "handoff"), ("Soy familiar de María, su DNI es 30222333", None)],
)
async def test_handoff_and_third_party_still_win_mid_intake(message, intent):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=message, collected_data=_INTAKE))

    assert result["intent"] == (intent or "third_party_guard")


@pytest.mark.asyncio
async def test_idle_conversations_keep_the_llm_routing():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="OSDE 210"))

    assert result["intent"] == "insurance"


class _IntakeExtractingLLM(FakeLLMProvider):
    async def extract_information(self, message, required_fields):
        found = {}
        if message.strip().casefold() == "osde 210":
            found = {"obra_social": "OSDE", "plan": "210"}
        found = {k: v for k, v in found.items() if k in required_fields}
        return ExtractionResult(
            fields=found, missing_fields=[f for f in required_fields if f not in found]
        )


@pytest.mark.asyncio
async def test_osde_210_during_the_intake_fills_obra_social_and_plan():
    llm = _IntakeExtractingLLM()
    resolve = create_resolve_interaction_node(llm)
    appointment, _, _ = await make_node_and_conversation(llm_provider=llm)
    state = make_agent_state(user_message="OSDE 210", collected_data=_INTAKE)

    routed = await resolve(state)
    result = await appointment({**state, **routed})  # type: ignore[typeddict-item]

    intake = result["collected_data"]["first_visit_intake"]
    assert intake["details"]["obra_social"] == "OSDE"
    assert intake["details"]["plan"] == "210"
    assert intake["stage"] == "review"


@pytest.mark.asyncio
async def test_trying_other_data_clears_both_name_and_dni():
    appointment, _, _ = await make_node_and_conversation()

    result = await appointment(
        make_agent_state(
            button_payload=PATIENT_NOT_FOUND_RETRY_PAYLOAD,
            collected_data={
                "stage": STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE,
                "identification_full_name": "Rosa Gomez",
                "identification_dni": "30999888",
            },
        )
    )

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert not data.get("identification_full_name")
    assert not data.get("identification_dni")


class _HandoffLLM(FakeLLMProvider):
    async def understand(self, message, context):
        from app.domain.repositories.llm_provider import UnderstandingResult

        return UnderstandingResult(intent="handoff", confidence=0.9)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message", ["no me siento bien, necesito que me atienda alguien ya", "esto es un desastre"]
)
@pytest.mark.parametrize(
    "stage", [STAGE_AWAITING_FIRST_VISIT_INTAKE, STAGE_AWAITING_IDENTIFICATION]
)
async def test_the_llm_handoff_intent_still_wins_in_a_data_stage(message, stage):
    node = create_resolve_interaction_node(_HandoffLLM())

    result = await node(make_agent_state(user_message=message, collected_data={"stage": stage}))

    assert result["intent"] == "handoff"
    assert result["interruption"] == "terminate"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["me duele mucho, es una urgencia", "quiero hacer un reclamo", "quiero hablar con un humano"],
)
@pytest.mark.parametrize(
    "stage", [STAGE_AWAITING_FIRST_VISIT_INTAKE, STAGE_AWAITING_IDENTIFICATION]
)
async def test_urgency_and_complaints_hand_off_mid_collection(message, stage):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=message, collected_data={"stage": stage}))

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_only_handoff_is_honoured_from_the_llm_in_a_data_stage():
    class _InsuranceLLM(FakeLLMProvider):
        async def understand(self, message, context):
            from app.domain.repositories.llm_provider import UnderstandingResult

            return UnderstandingResult(intent="insurance", confidence=0.95, answer="x")

    node = create_resolve_interaction_node(_InsuranceLLM())

    result = await node(make_agent_state(user_message="OSDE 210", collected_data=_INTAKE))

    assert result == {"intent": "appointment"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "atienden osde",
        "trabajan con swiss medical",
        "cuánto cubre el plan",
        "hay turnos los sábados",
    ],
)
async def test_an_inquiry_without_a_question_mark_is_answered_and_keeps_the_intake(message):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=message, collected_data=_INTAKE))

    assert result["intent"] in {"insurance", "question", "specialties", "unknown", "appointment"}
    assert result["intent"] != "appointment" or "interruption" not in result
    assert (
        "collected_data" not in result
        or result["collected_data"].get("first_visit_intake") == _INTAKE["first_visit_intake"]
    )


@pytest.mark.asyncio
async def test_atienden_osde_reaches_the_insurance_node_as_a_temporary_interruption():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="atienden osde", collected_data=_INTAKE))

    assert result["intent"] == "insurance"
    assert result["interruption"] == "temporary"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["osde 210", "Swiss Medical", "hay 30123456"])
async def test_data_looking_answers_stay_in_the_intake(answer):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=answer, collected_data=_INTAKE))

    assert result["intent"] == "appointment"
    assert result.get("interruption") is None


def test_the_stage_sets_use_the_stage_constants():
    from app.agent.nodes import resolve_interaction as module
    from app.agent.nodes.appointment import (
        STAGE_AWAITING_CONFIRMATION,
        STAGE_AWAITING_NEW_PATIENT_DETAILS,
    )

    assert module._THIRD_PARTY_STAGES_EXEMPT == frozenset({STAGE_AWAITING_CONFIRMATION})
    assert module._DATA_COLLECTION_STAGES == frozenset(
        {
            STAGE_AWAITING_FIRST_VISIT_INTAKE,
            STAGE_AWAITING_IDENTIFICATION,
            STAGE_AWAITING_NEW_PATIENT_DETAILS,
        }
    )
