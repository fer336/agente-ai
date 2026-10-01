import pytest

from app.agent.clinic_topics import CLINIC_TOPICS
from app.agent.nodes.faq_topic import create_faq_topic_node
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
)
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", CLINIC_TOPICS, ids=lambda topic: topic.id)
async def test_each_topic_returns_its_exact_text_and_the_three_buttons(topic):
    node = create_faq_topic_node()

    result = await node(make_agent_state(collected_data={"faq_topic_id": topic.id}))

    assert result["response_text"] == topic.text
    buttons = result["response_buttons"]
    assert [(button.id, button.title) for button in buttons] == [
        (
            "FAQ_BOOK:consulta_particular"
            if topic.id == "consulta_particular"
            else OPERATION_CREATE_PAYLOAD,
            "Agendar cita",
        ),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
        (MENU_ADMIN_PAYLOAD, "💬 Administración"),
    ]
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_the_topic_id_is_consumed_and_the_stage_is_preserved():
    node = create_faq_topic_node()
    state = make_agent_state(
        collected_data={
            "faq_topic_id": "alineadores",
            "stage": "awaiting_slot_selection",
            "chosen_professional_id": "p1",
        }
    )

    result = await node(state)

    assert "faq_topic_id" not in result["collected_data"]
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"
    assert result["collected_data"]["chosen_professional_id"] == "p1"


@pytest.mark.asyncio
async def test_without_a_state_id_the_topic_is_matched_from_the_message():
    node = create_faq_topic_node()

    result = await node(make_agent_state(user_message="cuánto sale el blanqueamiento?"))

    assert result["response_text"] == CLINIC_TOPICS[0].text


@pytest.mark.asyncio
async def test_the_state_id_wins_over_the_message():
    node = create_faq_topic_node()
    state = make_agent_state(
        user_message="blanqueamiento", collected_data={"faq_topic_id": "alineadores"}
    )

    result = await node(state)

    assert result["response_text"] == CLINIC_TOPICS[4].text


@pytest.mark.asyncio
async def test_an_unresolved_topic_shows_the_same_topic_list_as_the_menu():
    node = create_faq_topic_node()

    result = await node(
        make_agent_state(user_message="cuánto sale lo de los dientes", collected_data={})
    )

    assert "$" not in result["response_text"]
    assert result["response_buttons"] is None
    assert [row.id for row in result["response_list"].rows] == [
        topic.payload for topic in CLINIC_TOPICS
    ]
    assert "faq_topic_id" not in result["collected_data"]
    assert result["requires_handoff"] is False
