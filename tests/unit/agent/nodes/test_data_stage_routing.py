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
