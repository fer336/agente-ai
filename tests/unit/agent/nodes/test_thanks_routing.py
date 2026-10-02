import pytest

from app.agent.graph import _route_after_resolve_interaction
from app.agent.nodes.appointment import (
    STAGE_AWAITING_CONFIRMATION,
    STAGE_AWAITING_FIRST_VISIT_INTAKE,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_SLOT_SELECTION,
)
from app.agent.nodes.resolve_interaction import (
    POST_ACTION_CLOSE_INTENT,
    THANKS_INTENT,
    create_resolve_interaction_node,
)
from app.domain.repositories.llm_provider import ResponseContext, UnderstandingResult
from app.infrastructure.llm.exceptions import LLMProviderError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state

_FAKE_THANKS_REPLY = "De nada! Cualquier cosa, escribime."


class _RecordingLLMProvider(FakeLLMProvider):
    def __init__(self) -> None:
        self.understand_calls = 0
        self.response_contexts: list[ResponseContext] = []

    async def understand(self, message, context):
        self.understand_calls += 1
        return await super().understand(message, context)

    async def generate_response(self, context):
        self.response_contexts.append(context)
        return await super().generate_response(context)


class _FailingResponseLLMProvider(FakeLLMProvider):
    async def generate_response(self, context):
        raise LLMProviderError("boom")


def _stage_data(stage: str) -> dict[str, object]:
    return {"stage": stage, "especialidad": "Ortodoncia", "slot_id": "s-1"}


@pytest.mark.asyncio
async def test_idle_thanks_without_any_window_gets_a_thanks_reply_not_the_fallback():
    llm = _RecordingLLMProvider()
    node = create_resolve_interaction_node(llm)

    result = await node(make_agent_state(user_message="Gracias"))

    assert result["intent"] == THANKS_INTENT
    assert result["response_text"] == _FAKE_THANKS_REPLY
    assert result["response_buttons"] is None
    assert result["requires_handoff"] is False
    assert _route_after_resolve_interaction({"intent": result["intent"]}) == "__end__"  # type: ignore[arg-type]
    assert llm.understand_calls == 0
    context = llm.response_contexts[0]
    assert context.intent == "thanks"
    assert "situacion" in context.collected_data
    assert "instruccion" in context.collected_data
    assert "accion_completada" not in context.collected_data


@pytest.mark.asyncio
async def test_idle_thanks_keeps_the_existing_collected_data():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="gracias", collected_data={"specialty_mention": "ortodoncia"})
    )

    assert result["collected_data"] == {"specialty_mention": "ortodoncia"}


@pytest.mark.asyncio
async def test_thanks_right_after_a_completed_action_keeps_the_action_specific_close():
    llm = _RecordingLLMProvider()
    node = create_resolve_interaction_node(llm)

    result = await node(
        make_agent_state(
            user_message="Muchas gracias",
            collected_data={"post_action_context": "cancel_appointment"},
        )
    )

    assert result["intent"] == POST_ACTION_CLOSE_INTENT
    assert result["response_text"] == "Listo, quedó cancelado. Cualquier cosa, escribime."
    assert result["collected_data"] == {}
    assert result["response_buttons"] is None
    assert llm.response_contexts[0].collected_data["accion_completada"] == "cancel_appointment"


@pytest.mark.asyncio
async def test_thanks_after_a_completed_action_falls_back_to_the_static_text_when_the_llm_fails():
    node = create_resolve_interaction_node(_FailingResponseLLMProvider())

    result = await node(
        make_agent_state(
            user_message="gracias",
            collected_data={"post_action_context": "create_appointment"},
        )
    )

    assert result["response_text"] == "De nada! Ahí quedó anotado tu turno, te esperamos."
    assert result["collected_data"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [STAGE_AWAITING_SLOT_SELECTION, STAGE_AWAITING_CONFIRMATION])
async def test_thanks_mid_flow_preserves_the_stage_and_the_data(stage):
    llm = _RecordingLLMProvider()
    node = create_resolve_interaction_node(llm)
    data = _stage_data(stage)

    result = await node(
        make_agent_state(
            user_message="gracias", collected_data=dict(data), active_flow="appointment"
        )
    )

    assert result["intent"] == THANKS_INTENT
    assert result["response_text"] == _FAKE_THANKS_REPLY
    assert result["response_buttons"] is None
    assert result["collected_data"] == data
    assert "interruption" not in result
    assert "active_node" not in result
    assert "resume_node" not in result
    assert result["requires_handoff"] is False
    context = llm.response_contexts[0]
    assert "en curso" in str(context.collected_data["instruccion"])
    assert llm.understand_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["ok", "dale", "listo", "perfecto", "👍"])
async def test_bare_acknowledgements_inside_a_stage_are_not_intercepted(message):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message=message, collected_data=_stage_data(STAGE_AWAITING_SLOT_SELECTION)
        )
    )

    assert result["intent"] != THANKS_INTENT
    assert "response_text" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["ok", "Dale", "perfecto", "👍"])
async def test_a_bare_acknowledgement_while_idle_gets_the_thanks_reply(message):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message=message))

    assert result["intent"] == THANKS_INTENT
    assert result["response_text"] == _FAKE_THANKS_REPLY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", [STAGE_AWAITING_FIRST_VISIT_INTAKE, STAGE_AWAITING_IDENTIFICATION]
)
async def test_thanks_is_not_intercepted_in_the_data_collection_stages(stage):
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="gracias", collected_data={"stage": stage})
    )

    assert result["intent"] == "appointment"
    assert "response_text" not in result


@pytest.mark.asyncio
async def test_thanks_that_also_requests_something_routes_normally():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(make_agent_state(user_message="gracias, quiero un turno"))

    assert result["intent"] == "appointment"
    assert "response_text" not in result


@pytest.mark.asyncio
async def test_no_gracias_at_the_confirmation_stage_is_not_treated_as_thanks():
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="no gracias", collected_data=_stage_data(STAGE_AWAITING_CONFIRMATION)
        )
    )

    assert result["intent"] == "appointment"
    assert "response_text" not in result


@pytest.mark.asyncio
async def test_idle_thanks_falls_back_to_the_static_text_when_the_llm_fails():
    node = create_resolve_interaction_node(_FailingResponseLLMProvider())

    result = await node(make_agent_state(user_message="gracias"))

    assert result["intent"] == THANKS_INTENT
    assert result["response_text"] == "De nada! Cualquier cosa, escribime."


class _ThanksLabelLLMProvider(FakeLLMProvider):
    def __init__(self, confidence: float = 0.9) -> None:
        self._confidence = confidence

    async def understand(self, message, context):
        return UnderstandingResult(intent="thanks", confidence=self._confidence)


@pytest.mark.asyncio
async def test_a_paraphrased_thanks_labelled_by_the_llm_gets_the_same_reply():
    node = create_resolve_interaction_node(_ThanksLabelLLMProvider())

    result = await node(make_agent_state(user_message="te lo agradezco un montón, saludos"))

    assert result["intent"] == THANKS_INTENT
    assert result["response_text"] == _FAKE_THANKS_REPLY
    assert result["response_buttons"] is None


@pytest.mark.asyncio
async def test_a_low_confidence_thanks_label_is_not_trusted():
    node = create_resolve_interaction_node(_ThanksLabelLLMProvider(confidence=0.2))

    result = await node(make_agent_state(user_message="te lo agradezco un montón, saludos"))

    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_an_llm_thanks_label_mid_flow_preserves_the_stage_and_data():
    node = create_resolve_interaction_node(_ThanksLabelLLMProvider())
    data = _stage_data(STAGE_AWAITING_SLOT_SELECTION)

    result = await node(
        make_agent_state(user_message="te lo agradezco un montón", collected_data=dict(data))
    )

    assert result["intent"] == THANKS_INTENT
    assert result["collected_data"] == data
    assert "interruption" not in result


@pytest.mark.asyncio
async def test_an_llm_thanks_label_on_a_decline_is_vetoed():
    node = create_resolve_interaction_node(_ThanksLabelLLMProvider())

    result = await node(
        make_agent_state(
            user_message="no, gracias, mejor otro día",
            collected_data=_stage_data(STAGE_AWAITING_CONFIRMATION),
        )
    )

    assert result["intent"] == "appointment"


@pytest.mark.asyncio
async def test_an_llm_thanks_label_inside_a_data_stage_does_not_answer_thanks():
    node = create_resolve_interaction_node(_ThanksLabelLLMProvider())

    result = await node(
        make_agent_state(
            user_message="muy amable, gracias",
            collected_data={"stage": STAGE_AWAITING_IDENTIFICATION},
        )
    )

    assert result["intent"] == "appointment"
