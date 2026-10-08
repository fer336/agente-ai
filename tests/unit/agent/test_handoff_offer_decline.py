import pytest
from langgraph.graph import END

from app.agent.graph import HANDOFF_NODE, _route_after_resolve_interaction
from app.agent.handoff_offer import HANDOFF_OFFER_KEY, is_handoff_offer_decline
from app.agent.nodes.resolve_interaction import (
    HANDOFF_DECLINED_INTENT,
    HANDOFF_DECLINED_STATIC_MESSAGE,
    create_resolve_interaction_node,
)
from app.domain.value_objects.menu_payloads import MENU_MAIN_PAYLOAD
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_ycloud_handoff_gateway
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.parametrize(
    "text",
    [
        "no",
        "No",
        "nop",
        "No gracias",
        "no, gracias",
        "No muchas gracias",
        "por ahora no",
        "no por ahora",
        "No hace falta",
        "no necesito",
        "no quiero",
        "No, está bien",
        "No está bien",
        "no esta bien",
        "así está bien",
        "esta bien asi",
        "dejalo así",
        "no, dejalo",
        "no es necesario",
        "No, gracias!",
    ],
)
def test_short_refusals_are_declines(text):
    assert is_handoff_offer_decline(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "no sé",
        "no entiendo",
        "no puedo ir",
        "no me aparece el turno",
        "no llego",
        "no estoy conforme",
        "no me gusta",
        "sí",
        "dale",
        "quiero hablar con una persona",
        "no, quiero hablar con una persona",
        "no, voy a llegar tarde",
        "no gracias pero quiero cambiar el turno de mañana",
        "",
    ],
)
def test_everything_else_is_not_a_decline(text):
    assert is_handoff_offer_decline(text) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["No está bien", "No, está bien", "no gracias", "No"])
async def test_a_decline_after_an_offer_is_answered_without_handoff_or_llm(reply):
    class _ExplodingLLM(FakeLLMProvider):
        async def understand(self, message, context):
            raise AssertionError("the LLM must not classify a decline")

    node = create_resolve_interaction_node(_ExplodingLLM())

    result = await node(
        make_agent_state(user_message=reply, collected_data={HANDOFF_OFFER_KEY: True})
    )

    assert result["intent"] == HANDOFF_DECLINED_INTENT
    assert result["intent"] != "handoff"
    assert result["response_text"] == HANDOFF_DECLINED_STATIC_MESSAGE
    assert result["requires_handoff"] is False
    assert [button.id for button in result["response_buttons"]] == [MENU_MAIN_PAYLOAD]
    assert HANDOFF_OFFER_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_decline_keeps_the_active_stage():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="no gracias",
            collected_data={HANDOFF_OFFER_KEY: True, "stage": "awaiting_slot_selection"},
        )
    )

    assert result["intent"] == HANDOFF_DECLINED_INTENT
    assert result["collected_data"] == {"stage": "awaiting_slot_selection"}


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["Bueno", "dale", "Sí"])
async def test_accepting_the_offer_still_hands_off(reply):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message=reply, collected_data={HANDOFF_OFFER_KEY: True})
    )

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["no, quiero hablar con una persona", "No, voy a llegar tarde", "No aparece mi turno"],
)
async def test_automatic_handoff_phrases_keep_priority_over_a_decline(message):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message=message, collected_data={HANDOFF_OFFER_KEY: True})
    )

    assert result["intent"] == "handoff"


@pytest.mark.asyncio
async def test_a_no_without_a_pending_offer_takes_the_normal_path():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="no gracias", collected_data={}))

    assert result["intent"] != HANDOFF_DECLINED_INTENT


@pytest.mark.asyncio
async def test_a_button_tap_is_never_read_as_a_decline():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="no",
            button_payload=MENU_MAIN_PAYLOAD,
            collected_data={HANDOFF_OFFER_KEY: True},
        )
    )

    assert result["intent"] != HANDOFF_DECLINED_INTENT


@pytest.mark.asyncio
async def test_the_declined_turn_ends_the_graph_and_never_reaches_the_handoff_gateway():
    handoff_gateway = make_ycloud_handoff_gateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    node = create_resolve_interaction_node(FakeLLMProvider())

    state = make_agent_state(user_message="No está bien", collected_data={HANDOFF_OFFER_KEY: True})
    update = await node(state)
    merged = {**state, **update}

    route = _route_after_resolve_interaction(merged)  # type: ignore[arg-type]
    assert route == END
    assert route != HANDOFF_NODE
    assert merged["response_text"] == HANDOFF_DECLINED_STATIC_MESSAGE
    assert handoff_gateway.handoff_requests == []
    conversation = await conversation_repository.get_by_id(make_conversation(id_="conv-1").id)
    assert conversation is not None
    assert conversation.mode == "agent"
