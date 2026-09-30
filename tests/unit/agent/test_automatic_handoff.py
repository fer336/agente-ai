"""PRD.md §22 automatic-handoff phrases, detected before the LLM intent (audit v0.44.0)."""

import pytest

from app.agent.automatic_handoff import requires_automatic_handoff
from app.agent.graph import HANDOFF_NODE, _route_after_resolve_interaction
from app.agent.nodes.handoff import create_handoff_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import UnderstandingResult
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.llm.openai_compatible_llm_provider import (
    DEFAULT_CLASSIFY_INTENT_PROMPT,
    DEFAULT_UNDERSTAND_PROMPT,
)
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_ycloud_handoff_gateway
from tests.fixtures.seed_objects import make_conversation

_PRD_PHRASES = [
    "Voy a llegar tarde",
    "voy a llegar tarde, avisales",
    "Llego tarde",
    "llego tardeee",
    "Estoy llegando",
    "estoy llegando!",
    "Ya llego",
    "No aparece mi turno",
    "no me aparece el turno",
    "Me equivoqué con el turno",
    "me equivoque con el turno",
    "Tengo un problema con mi turno",
    "TENGO UN PROBLEMA CON MI TURNO.",
    "Necesito hablar con una persona",
    "quiero hablar con alguien",
    "hablar con administración",
    "quiero hablar con un asesor",
]


@pytest.mark.parametrize("message", _PRD_PHRASES)
def test_the_matcher_recognizes_the_prd_phrases(message):
    assert requires_automatic_handoff(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Quiero sacar un turno",
        "no voy a llegar tarde",
        "no llego tarde, tranquila",
        "¿cómo llegar a la clínica?",
        "Pedro Cassera 30131313",
        "prefiero un turno temprano",
        "mi turno es el lunes",
        "",
    ],
)
def test_the_matcher_ignores_ordinary_messages(message):
    assert requires_automatic_handoff(message) is False


class _MisclassifyingLLM(FakeLLMProvider):
    """The real model read these phrases as an appointment request (audit)."""

    async def understand(self, message, context):
        return UnderstandingResult(
            intent="appointment", confidence=0.95, operation_mention="create"
        )


class _ExplodingLLM(FakeLLMProvider):
    async def understand(self, message, context):
        raise AssertionError("the LLM must not be consulted for a PRD §22 phrase")


@pytest.mark.asyncio
@pytest.mark.parametrize("message", _PRD_PHRASES)
async def test_the_prd_phrases_hand_off_before_the_llm_is_consulted(message):
    node = create_resolve_interaction_node(_ExplodingLLM())

    result = await node(make_agent_state(user_message=message))

    assert result["intent"] == "handoff"
    assert result["interruption"] == "terminate"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["awaiting_confirmation", "awaiting_identification", "awaiting_slot"]
)
async def test_the_phrases_also_escape_an_active_stage_like_the_existing_handoff_phrases(stage):
    node = create_resolve_interaction_node(_ExplodingLLM())

    result = await node(
        make_agent_state(user_message="Voy a llegar tarde", collected_data={"stage": stage})
    )

    assert result["intent"] == "handoff"
    assert result["interruption"] == "terminate"


@pytest.mark.asyncio
async def test_a_button_tap_is_never_matched_as_a_phrase():
    node = create_resolve_interaction_node(_MisclassifyingLLM())

    result = await node(
        make_agent_state(
            user_message="Estoy llegando",
            button_payload="CONFIRM_APPOINTMENT",
            collected_data={"stage": "awaiting_confirmation"},
        )
    )

    assert result == {"intent": "appointment"}


@pytest.mark.asyncio
async def test_the_phrase_drops_a_pending_post_action_window():
    node = create_resolve_interaction_node(_ExplodingLLM())

    result = await node(
        make_agent_state(
            user_message="No aparece mi turno",
            collected_data={"post_action_context": "create_appointment"},
        )
    )

    assert result["intent"] == "handoff"
    assert "post_action_context" not in result.get("collected_data", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Voy a llegar tarde", "Estoy llegando", "No aparece mi turno"])
async def test_audit_replay_hands_the_conversation_off_instead_of_asking_for_dni(message):
    handoff_gateway = make_ycloud_handoff_gateway()
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    resolve = create_resolve_interaction_node(_MisclassifyingLLM())
    handoff = create_handoff_node(handoff_gateway, conversation_repository)

    state = make_agent_state(user_message=message)
    update = await resolve(state)
    assert _route_after_resolve_interaction({**state, **update}) == HANDOFF_NODE  # type: ignore[typeddict-item]
    result = await handoff({**state, **update})  # type: ignore[typeddict-item]

    assert result["requires_handoff"] is True
    conversation = await conversation_repository.get_by_id(make_conversation(id_="conv-1").id)
    assert conversation is not None
    assert conversation.mode == "human"


@pytest.mark.parametrize("prompt", [DEFAULT_CLASSIFY_INTENT_PROMPT, DEFAULT_UNDERSTAND_PROMPT])
@pytest.mark.parametrize(
    "example", ["voy a llegar tarde", "estoy llegando", "no aparece mi", "tengo un problema con mi"]
)
def test_both_intent_prompts_list_the_prd_handoff_examples(prompt, example):
    assert example in prompt
