"""`FAQ_BOOK:<topic>`: the topic answer's "Agendar cita" button; every frequent topic books
the fixed Dentalink specialty "General"."""

import pytest

from app.agent.clinic_topics import (
    ALIGNERS_SPECIALTY_ID,
    CLINIC_TOPICS,
    PRESELECTED_SPECIALTY_KEY,
    topic_by_id,
)
from app.agent.nodes.faq_topic import create_faq_topic_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import UnderstandingResult
from app.domain.value_objects.menu_payloads import (
    FAQ_BOOK_PAYLOAD_PREFIX,
    faq_book_payload,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state

_BOOK_CONSULTA = "FAQ_BOOK:consulta_particular"


class _BookingLLM(FakeLLMProvider):
    async def understand(self, message, context):
        return UnderstandingResult(intent="appointment", confidence=0.9, operation_mention="create")


def test_the_payload_helper_builds_a_short_prefixed_id():
    payload = faq_book_payload("consulta_particular")

    assert payload == _BOOK_CONSULTA
    assert payload.startswith(FAQ_BOOK_PAYLOAD_PREFIX)
    assert all(len(faq_book_payload(topic.id)) <= 256 for topic in CLINIC_TOPICS)


def test_every_frequent_topic_books_the_general_specialty_except_the_alineadores():
    booking = {topic.id: topic.book_specialty for topic in CLINIC_TOPICS}

    assert booking == {
        "blanqueamiento": "General",
        "consulta_particular": "General",
        "limpieza_particular": "General",
        "brackets_obra_social": "General",
        "alineadores": ALIGNERS_SPECIALTY_ID,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic", [t for t in CLINIC_TOPICS if t.id != "alineadores"], ids=lambda topic: topic.id
)
async def test_the_topic_node_offers_the_topic_book_button(topic):
    result = await create_faq_topic_node()(
        make_agent_state(collected_data={"faq_topic_id": topic.id})
    )

    first = result["response_buttons"][0]
    assert (first.id, first.title) == (f"FAQ_BOOK:{topic.id}", "Agendar cita")


@pytest.mark.asyncio
async def test_an_idle_book_tap_starts_the_create_flow_with_the_preselected_specialty():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(button_payload=_BOOK_CONSULTA, user_message="Agendar cita")
    )

    assert result["intent"] == "appointment"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
async def test_a_mid_flow_book_tap_replaces_the_flow_and_carries_the_specialty():
    node = create_resolve_interaction_node(FakeLLMProvider())
    stale = {"stage": "awaiting_slot_selection", "chosen_specialty_id": "spec-1"}

    result = await node(make_agent_state(button_payload=_BOOK_CONSULTA, collected_data=stale))

    assert result["intent"] == "appointment"
    assert result["interruption"] == "replace"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_id", ["limpieza_particular", "brackets_obra_social"])
async def test_a_book_tap_for_limpieza_or_brackets_preselects_the_general_specialty(topic_id):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(button_payload=f"FAQ_BOOK:{topic_id}"))

    assert result["intent"] == "appointment"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
async def test_a_book_tap_for_the_blanqueamiento_preselects_the_general_specialty():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(button_payload="FAQ_BOOK:blanqueamiento", user_message="Agendar cita")
    )

    assert result["intent"] == "appointment"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "quiero un turno para consulta particular",
        "quiero un turno para blanqueamiento",
        "necesito una cita particular",
        "Quiero agendar una consulta particular",
    ],
)
async def test_a_free_text_booking_of_a_consulta_particular_carries_the_specialty(message):
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(make_agent_state(user_message=message))

    assert result["intent"] == "appointment"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
async def test_a_free_text_booking_of_a_limpieza_carries_the_general_specialty():
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(make_agent_state(user_message="quiero un turno para limpieza"))

    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    ["awaiting_first_visit_intake", "awaiting_identification", "awaiting_new_patient_details"],
)
async def test_the_specialty_is_never_preselected_inside_a_data_stage(stage):
    node = create_resolve_interaction_node(_BookingLLM())

    result = await node(
        make_agent_state(
            user_message="quiero un turno para consulta particular",
            collected_data={"stage": stage},
        )
    )

    assert PRESELECTED_SPECIALTY_KEY not in result.get("collected_data", {})


def test_the_consulta_particular_topic_is_the_one_that_books_general():
    topic = topic_by_id("consulta_particular")

    assert topic is not None and topic.book_specialty == "General"
