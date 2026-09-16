import pytest

from app.agent.nodes.question import create_question_node
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_question_delivers_answer_without_destroying_active_stage():
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(
        collected_data={
            "stage": "awaiting_slot_selection",
            "pending_answer": "Sí, atendemos los sábados.",
            "chosen_professional_id": "p1",
        }
    )

    result = await node(state)

    assert result["response_text"] == "Sí, atendemos los sábados."
    assert result["response_buttons"] is None
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
async def test_question_fails_closed_through_the_llm_when_no_answer_is_available():
    # Regression: an absent `pending_answer` used to return a hardcoded
    # string directly — now it's LLM-worded too (with a static fallback
    # for when the LLM call itself fails), same "no hardcoded default"
    # direction as every other node in this session.
    node = create_question_node(FakeLLMProvider())
    state = make_agent_state(collected_data={"stage": None})

    result = await node(state)

    assert result["response_text"] == "[fake-response for intent=question_unknown_answer]"
    assert result["response_buttons"] is None
