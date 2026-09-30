"""Audit v0.44.0: an answer offering "te pase con administración" carried no buttons."""

import pytest

from app.agent.handoff_offer import (
    HANDOFF_OFFER_BUTTONS,
    HANDOFF_OFFER_FLAG_KEY,
    HANDOFF_OFFER_KEY,
    offers_administration_handoff,
)
from app.agent.nodes.fallback import create_fallback_node
from app.agent.nodes.question import create_question_node
from app.agent.nodes.resolve_interaction import create_resolve_interaction_node
from app.domain.repositories.llm_provider import UnderstandingResult
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.llm.openai_compatible_llm_provider import DEFAULT_UNDERSTAND_PROMPT
from tests.fixtures.agent_state import make_agent_state

_AUDIT_ANSWER = (
    "Sí, atendemos pacientes particulares y también trabajamos con diversas obras sociales. "
    "¿Te gustaría que te pase con administración para consultar por tu cobertura específica?"
)
#: An offer worded so that no regex would ever recognise it.
_UNDETECTABLE_OFFER = "Eso lo ve mejor el equipo de la clínica, ¿lo derivamos?"


@pytest.mark.parametrize(
    "text",
    [
        _AUDIT_ANSWER,
        "¿Te gustaría que te comunique con administración?",
        "Si te gusta, te gustaría que te derive con Administración para confirmarlo.",
    ],
)
def test_the_text_detector_also_recognizes_the_te_gustaria_que_te_pase_offer(text):
    assert offers_administration_handoff(text) is True


def test_the_understand_prompt_asks_for_the_boolean_handoff_offer_field():
    assert '"handoff_offer": <true|false>' in DEFAULT_UNDERSTAND_PROMPT


class _AnsweringLLM(FakeLLMProvider):
    def __init__(self, answer: str, *, handoff_offer: bool) -> None:
        super().__init__()
        self._answer = answer
        self._flag = handoff_offer

    async def understand(self, message, context):
        return UnderstandingResult(
            intent="question", confidence=0.95, answer=self._answer, handoff_offer=self._flag
        )


@pytest.mark.asyncio
async def test_the_router_carries_the_flag_for_the_question_node():
    node = create_resolve_interaction_node(_AnsweringLLM(_UNDETECTABLE_OFFER, handoff_offer=True))

    result = await node(make_agent_state(user_message="¿atienden por sistema de salud?"))

    assert result["collected_data"]["pending_answer"] == _UNDETECTABLE_OFFER
    assert result["collected_data"][HANDOFF_OFFER_FLAG_KEY] is True


@pytest.mark.asyncio
async def test_the_router_carries_no_flag_when_the_answer_does_not_offer_a_handoff():
    node = create_resolve_interaction_node(
        _AnsweringLLM("Atendemos de 9 a 18.", handoff_offer=False)
    )

    result = await node(make_agent_state(user_message="¿horarios?"))

    assert HANDOFF_OFFER_FLAG_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_stale_flag_never_outlives_its_turn():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="quiero un turno",
            collected_data={HANDOFF_OFFER_FLAG_KEY: True, "pending_answer": "x"},
        )
    )

    assert HANDOFF_OFFER_FLAG_KEY not in result["collected_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("node_factory", [create_question_node, create_fallback_node])
@pytest.mark.parametrize(
    ("answer", "flag"),
    [
        (_UNDETECTABLE_OFFER, True),  # flag path
        (_AUDIT_ANSWER, False),  # detector path (the audit miss)
        (_AUDIT_ANSWER, True),
    ],
)
async def test_an_answer_that_offers_a_handoff_shows_the_offer_buttons(node_factory, answer, flag):
    node = node_factory(FakeLLMProvider())
    collected_data = {"pending_answer": answer}
    if flag:
        collected_data[HANDOFF_OFFER_FLAG_KEY] = True

    result = await node(make_agent_state(user_message="hola", collected_data=collected_data))

    assert result["response_text"] == answer
    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS
    assert result["collected_data"][HANDOFF_OFFER_KEY] is True
    assert HANDOFF_OFFER_FLAG_KEY not in result["collected_data"]
    assert "pending_answer" not in result["collected_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("node_factory", [create_question_node, create_fallback_node])
async def test_an_ordinary_answer_shows_no_offer_buttons(node_factory):
    node = node_factory(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="hola", collected_data={"pending_answer": "Atendemos de 9 a 18."}
        )
    )

    assert result["response_buttons"] != HANDOFF_OFFER_BUTTONS
    assert HANDOFF_OFFER_KEY not in result["collected_data"]


@pytest.mark.asyncio
async def test_audit_replay_through_the_router_and_the_question_node():
    resolve = create_resolve_interaction_node(_AnsweringLLM(_AUDIT_ANSWER, handoff_offer=False))
    question = create_question_node(FakeLLMProvider())
    state = make_agent_state(user_message="¿atienden particulares o solo obras sociales?")

    routed = await resolve(state)
    result = await question({**state, **routed})  # type: ignore[typeddict-item]

    assert routed["intent"] == "question"
    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS


@pytest.mark.asyncio
@pytest.mark.parametrize("node_factory", [create_question_node, create_fallback_node])
async def test_the_flag_is_ignored_when_the_guard_replaced_the_answer(node_factory):
    node = node_factory(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="hola",
            collected_data={
                "pending_answer": "Dale, ahí te lo confirmo. ¿Querés hablar con alguien?",
                HANDOFF_OFFER_FLAG_KEY: True,
            },
        )
    )

    assert "Todavía no se hizo ningún cambio" in result["response_text"]
    assert result["response_buttons"] != HANDOFF_OFFER_BUTTONS
    assert HANDOFF_OFFER_KEY not in result["collected_data"]
