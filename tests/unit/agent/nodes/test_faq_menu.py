import pytest

from app.agent.clinic_topics import CLINIC_TOPICS
from app.agent.nodes.faq_topic import create_faq_topic_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.value_objects.menu_payloads import MENU_FAQ_PAYLOAD
from app.domain.value_objects.welcome_menu import WELCOME_LIST
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


def test_the_welcome_menu_has_a_frequent_topics_row():
    rows = {row.id: row for row in WELCOME_LIST.rows}

    row = rows[MENU_FAQ_PAYLOAD]
    assert row.title == "ℹ️ Consultas frecuentes"
    assert len(row.title) <= 24
    assert row.description is not None and len(row.description) <= 72
    assert len(WELCOME_LIST.rows) == 7


@pytest.mark.asyncio
async def test_the_menu_payload_routes_to_the_faq_topic_intent_without_a_topic():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(button_payload=MENU_FAQ_PAYLOAD))

    assert result["intent"] == "faq_topic"
    assert "faq_topic_id" not in result.get("collected_data", {})


@pytest.mark.asyncio
async def test_the_menu_payload_mid_booking_interrupts_and_preserves_the_stage():
    node = create_resolve_interaction_node(FakeLLMProvider())
    collected = {"stage": "awaiting_slot_selection", "chosen_professional_id": "p1"}

    result = await node(make_agent_state(button_payload=MENU_FAQ_PAYLOAD, collected_data=collected))

    assert result["intent"] == "faq_topic"
    assert result["interruption"] == "temporary"
    assert result["resume_node"] == "awaiting_slot_selection"
    assert "faq_topic_id" not in result.get("collected_data", collected)


@pytest.mark.asyncio
async def test_the_node_answers_the_menu_payload_with_the_five_topic_list():
    result = await create_faq_topic_node()(
        make_agent_state(user_message="ℹ️ Consultas frecuentes", button_payload=MENU_FAQ_PAYLOAD)
    )

    response_list = result["response_list"]
    assert [(row.id, row.title) for row in response_list.rows] == [
        (topic.payload, topic.title) for topic in CLINIC_TOPICS
    ]
    assert len(response_list.rows) == 5
    assert all(len(row.title) <= 24 for row in response_list.rows)
    assert result["response_text"]
    assert result.get("response_buttons") is None
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_the_sub_list_preserves_the_booking_data():
    collected = {"stage": "awaiting_slot_selection", "chosen_professional_id": "p1"}

    result = await create_faq_topic_node()(
        make_agent_state(button_payload=MENU_FAQ_PAYLOAD, collected_data=collected)
    )

    assert result["collected_data"] == collected


@pytest.mark.asyncio
@pytest.mark.parametrize("topic", CLINIC_TOPICS, ids=lambda topic: topic.id)
async def test_each_sub_list_row_reaches_its_topic_text_through_resolve_and_the_node(topic):
    resolve = create_resolve_interaction_node(FakeLLMProvider())
    sub_list = await create_faq_topic_node()(make_agent_state(button_payload=MENU_FAQ_PAYLOAD))
    tapped = next(row for row in sub_list["response_list"].rows if row.id == topic.payload)

    routed = await resolve(make_agent_state(button_payload=tapped.id, user_message=tapped.title))
    answer = await create_faq_topic_node()(
        make_agent_state(
            button_payload=tapped.id,
            user_message=tapped.title,
            collected_data=routed["collected_data"],
        )
    )

    assert routed["intent"] == "faq_topic"
    assert answer["response_text"] == topic.text
    assert answer.get("response_list") is None
