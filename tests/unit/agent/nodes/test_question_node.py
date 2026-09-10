import pytest

from app.agent.nodes.question import question_node
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_question_delivers_answer_without_destroying_active_stage():
    state = make_agent_state(
        collected_data={
            "stage": "awaiting_slot_selection",
            "pending_answer": "Sí, atendemos los sábados.",
            "chosen_professional_id": "p1",
        }
    )

    result = await question_node(state)

    assert result["response_text"] == "Sí, atendemos los sábados."
    assert result["response_buttons"] is None
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"
    assert "pending_answer" not in result["collected_data"]
