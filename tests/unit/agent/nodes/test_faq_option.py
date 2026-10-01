"""Alineadores: the price image with three `Opción n` buttons; each option starts the
booking on the "General" specialty and is remembered until the confirmation."""

import pytest

from app.agent.clinic_topics import (
    ALIGNER_OPTION_KEY,
    CLINIC_TOPICS,
    PRESELECTED_SPECIALTY_KEY,
    topic_by_id,
)
from app.agent.first_visit_intake_subgraph import FIRST_VISIT_CANCEL_PAYLOAD
from app.agent.nodes.appointment import (
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.agent.nodes.appointment_selection import STAGE_AWAITING_SLOT_SELECTION
from app.agent.nodes.faq_topic import create_faq_topic_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.value_objects.menu_payloads import (
    FAQ_OPTION_PAYLOAD_PREFIX,
    faq_option_payload,
    parse_faq_option_payload,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation
from tests.unit.agent.nodes.test_faq_book_booking import _PATIENT, _general_world

_IMAGE_URL = "https://agent.example.com/public/alineadores-opciones.jpg"
_OPTION_2 = "FAQ_OPTION:alineadores:2"


def test_the_option_payload_helper_builds_and_parses_a_short_prefixed_id():
    payload = faq_option_payload("alineadores", "2")

    assert payload == _OPTION_2
    assert payload.startswith(FAQ_OPTION_PAYLOAD_PREFIX)
    assert parse_faq_option_payload(payload) == ("alineadores", "2")


@pytest.mark.parametrize(
    "payload", ["FAQ_OPTION:", "FAQ_OPTION:alineadores", "FAQ_BOOK:alineadores:2", "nope", ""]
)
def test_a_malformed_option_payload_does_not_parse(payload):
    assert parse_faq_option_payload(payload) is None


def test_alineadores_carries_the_image_the_three_options_and_the_general_specialty():
    topic = topic_by_id("alineadores")

    assert topic is not None
    assert topic.image_filename == "alineadores-opciones.jpg"
    assert topic.options == ("1", "2", "3")
    assert topic.book_specialty == "General"
    assert len(topic.text) <= 1024


def test_only_alineadores_has_an_image_and_options():
    others = [topic for topic in CLINIC_TOPICS if topic.id != "alineadores"]

    assert all(topic.image_filename is None and topic.options == () for topic in others)


@pytest.mark.asyncio
async def test_the_alineadores_answer_is_the_image_with_exactly_the_three_option_buttons():
    node = create_faq_topic_node(_IMAGE_URL)

    result = await node(make_agent_state(collected_data={"faq_topic_id": "alineadores"}))

    assert result["response_image_url"] == _IMAGE_URL
    assert result["response_text"] == topic_by_id("alineadores").text  # type: ignore[union-attr]
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (_OPTION_2.replace(":2", f":{n}"), f"Opción {n}") for n in ("1", "2", "3")
    ]
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_without_an_image_url_the_options_are_sent_as_text_only():
    node = create_faq_topic_node()

    result = await node(make_agent_state(user_message="cuánto salen los alineadores"))

    assert result.get("response_image_url") is None
    assert [b.title for b in result["response_buttons"]] == ["Opción 1", "Opción 2", "Opción 3"]


@pytest.mark.asyncio
async def test_other_topics_never_carry_the_image():
    node = create_faq_topic_node(_IMAGE_URL)

    result = await node(make_agent_state(collected_data={"faq_topic_id": "blanqueamiento"}))

    assert result.get("response_image_url") is None
    assert len(result["response_buttons"]) == 3
    assert result["response_buttons"][0].title == "Agendar cita"


@pytest.mark.asyncio
async def test_an_idle_option_tap_starts_the_create_flow_on_general_and_remembers_the_option():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(button_payload=_OPTION_2, user_message="Opción 2"))

    assert result["intent"] == "appointment"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"
    assert result["collected_data"][ALIGNER_OPTION_KEY] == "2"
    assert "interruption" not in result


@pytest.mark.asyncio
async def test_a_mid_flow_option_tap_replaces_the_flow_and_carries_both_keys():
    node = create_resolve_interaction_node(FakeLLMProvider())
    stale = {"stage": "awaiting_slot_selection", "chosen_specialty_id": "spec-1"}

    result = await node(
        make_agent_state(button_payload="FAQ_OPTION:alineadores:3", collected_data=stale)
    )

    assert result["intent"] == "appointment"
    assert result["interruption"] == "replace"
    assert result["collected_data"][PRESELECTED_SPECIALTY_KEY] == "General"
    assert result["collected_data"][ALIGNER_OPTION_KEY] == "3"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "FAQ_OPTION:alineadores:9",
        "FAQ_OPTION:nope:1",
        "FAQ_OPTION:blanqueamiento:1",
        "FAQ_OPTION:alineadores",
    ],
)
async def test_an_unknown_option_falls_through_like_an_unknown_payload(payload):
    node = create_resolve_interaction_node(FakeLLMProvider())

    idle = await node(make_agent_state(button_payload=payload))
    mid_flow = await node(
        make_agent_state(
            button_payload=payload, collected_data={"stage": "awaiting_slot_selection"}
        )
    )

    assert idle["intent"] == "unknown"
    assert ALIGNER_OPTION_KEY not in idle.get("collected_data", {})
    assert mid_flow["intent"] == "appointment"
    assert "interruption" not in mid_flow
    assert ALIGNER_OPTION_KEY not in mid_flow.get("collected_data", {})


async def _node():
    world = _general_world()
    node, _, _ = await make_node_and_conversation(
        available_slots=world["available_slots"],
        professionals=world["professionals"],
        specialties=world["specialties"],
    )
    return node


def _option_state(**overrides):
    base = {
        "button_payload": _OPTION_2,
        "user_message": "Opción 2",
        "collected_data": {PRESELECTED_SPECIALTY_KEY: "General", ALIGNER_OPTION_KEY: "2"},
    }
    return make_agent_state(**{**base, **overrides})


@pytest.mark.asyncio
async def test_a_new_patient_gets_the_first_visit_question_first_and_keeps_both_keys():
    node = await _node()

    result = await node(_option_state())

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_FIRST_VISIT_INTAKE
    assert data[PRESELECTED_SPECIALTY_KEY] == "General"
    assert data[ALIGNER_OPTION_KEY] == "2"
    assert result["response_buttons"] is not None


@pytest.mark.asyncio
async def test_after_the_intake_the_option_is_still_remembered_on_the_general_slots():
    node = await _node()
    question = await node(
        _option_state(
            collected_data={
                PRESELECTED_SPECIALTY_KEY: "General",
                ALIGNER_OPTION_KEY: "2",
                "identification_full_name": "Juan Perez",
                "identification_dni": "30123456",
            }
        )
    )

    result = await node(
        make_agent_state(
            button_payload=FIRST_VISIT_CANCEL_PAYLOAD, collected_data=question["collected_data"]
        )
    )

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["chosen_specialty_name"] == "General"
    assert data[ALIGNER_OPTION_KEY] == "2"


@pytest.mark.asyncio
async def test_a_known_patient_goes_straight_to_the_general_slots():
    node = await _node()

    result = await node(_option_state(patient_identity=_PATIENT))

    assert result["collected_data"]["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert result["collected_data"]["chosen_specialty_id"] == "gen"
    assert result["collected_data"][ALIGNER_OPTION_KEY] == "2"


@pytest.mark.asyncio
async def test_a_mid_flow_option_tap_keeps_the_option_across_the_reset():
    node = await _node()
    stale = {
        "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
        "operation": "create_appointment",
        "chosen_specialty_id": "odo",
        PRESELECTED_SPECIALTY_KEY: "General",
        ALIGNER_OPTION_KEY: "2",
    }

    result = await node(_option_state(collected_data=stale, patient_identity=_PATIENT))

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_SLOT_SELECTION
    assert data["chosen_specialty_id"] == "gen"
    assert data[ALIGNER_OPTION_KEY] == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["OPERATION_CANCEL", "OPERATION_RESCHEDULE", "OPERATION_VIEW"])
async def test_a_non_booking_operation_drops_the_option(payload):
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload=payload,
            collected_data={PRESELECTED_SPECIALTY_KEY: "General", ALIGNER_OPTION_KEY: "2"},
        )
    )

    assert ALIGNER_OPTION_KEY not in result["collected_data"]
    assert PRESELECTED_SPECIALTY_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_main_menu_tap_clears_the_option():
    node = await _node()

    result = await node(
        make_agent_state(
            button_payload="MENU_MAIN",
            collected_data={
                "stage": STAGE_AWAITING_FIRST_VISIT_INTAKE,
                PRESELECTED_SPECIALTY_KEY: "General",
                ALIGNER_OPTION_KEY: "2",
            },
        )
    )

    assert result["collected_data"] == {}


@pytest.mark.asyncio
async def test_the_confirmation_message_mentions_the_chosen_option():
    node = await _node()
    offered = await node(_option_state(patient_identity=_PATIENT))

    result = await node(
        make_agent_state(
            button_payload="SELECT_SLOT:slot-gen",
            collected_data=offered["collected_data"],
            patient_identity=_PATIENT,
        )
    )

    assert result["collected_data"]["stage"] == "awaiting_confirmation"
    assert "Consulta por alineadores: Opción 2" in result["response_text"]


@pytest.mark.asyncio
async def test_a_confirmation_without_an_option_has_no_aligner_line():
    node = await _node()
    offered = await node(
        make_agent_state(
            button_payload="FAQ_BOOK:consulta_particular",
            collected_data={PRESELECTED_SPECIALTY_KEY: "General"},
            patient_identity=_PATIENT,
        )
    )

    result = await node(
        make_agent_state(
            button_payload="SELECT_SLOT:slot-gen",
            collected_data=offered["collected_data"],
            patient_identity=_PATIENT,
        )
    )

    assert "alineadores" not in result["response_text"]
