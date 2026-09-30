"""A kinship claim never leads to acting on someone else's data (audit v0.44.0)."""

import pytest
from langgraph.graph import END

from app.agent.graph import _route_after_resolve_interaction
from app.agent.handoff_offer import HANDOFF_OFFER_BUTTONS, HANDOFF_OFFER_KEY
from app.agent.nodes.resolve_interaction import (
    THIRD_PARTY_GUARD_INTENT,
    create_resolve_interaction_node,
)
from app.agent.third_party_guard import (
    THIRD_PARTY_STATIC_MESSAGE,
    claims_to_act_for_someone_else,
)
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state

_AUDIT_MESSAGE = "Soy familiar de María López, cambiale el turno. Su DNI es 30222333"


@pytest.mark.parametrize(
    "message",
    [
        _AUDIT_MESSAGE,
        "soy familiar de un paciente",
        "Mi mamá tiene turno el lunes",
        "mi papá necesita cancelar su turno",
        "Quiero sacar un turno para mi hijo",
        "es para mi mamá, Rosa Gómez 30123456",
        "turno de mi esposa",
        "Necesito un turno a nombre de Rosa Gómez",
        "cancelale el turno a mi hija",
        "su DNI es 30222333",
        "sacale un turno a mi marido",
    ],
)
def test_the_matcher_recognizes_a_third_party_claim(message):
    assert claims_to_act_for_someone_else(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Pedro Cassera 30131313",
        "Rosa Gómez, 30123456",
        "Quiero sacar un turno",
        "Necesito cambiar mi turno",
        "mi DNI es 30123456",
        "mi mamá me recomendó la clínica",
        "Soy Marta, hola",
        "",
    ],
)
def test_the_matcher_lets_a_patients_own_data_through(message):
    assert claims_to_act_for_someone_else(message) is False


class _RecordingLLM(FakeLLMProvider):
    def __init__(self, reply: str | Exception) -> None:
        super().__init__()
        self._reply = reply
        self.contexts: list[ResponseContext] = []
        self.understood = False

    async def understand(self, message, context):
        self.understood = True
        return await super().understand(message, context)

    async def generate_response(self, context: ResponseContext) -> str:
        self.contexts.append(context)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


_SAFE_REPLY = (
    "Solo puedo ayudarte con tus propios turnos. Pasame tu nombre completo y tu DNI, "
    "o si preferís te conecto con un asesor."
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "collected_data",
    [
        {},
        {"stage": "awaiting_identification"},
        {"stage": "awaiting_first_visit_intake", "first_visit_intake": {"stage": "collect"}},
        {"stage": "awaiting_operation_selection"},
    ],
)
async def test_audit_replay_stops_before_the_llm_and_any_lookup(collected_data):
    llm = _RecordingLLM(_SAFE_REPLY)
    node = create_resolve_interaction_node(llm)

    result = await node(
        make_agent_state(user_message=_AUDIT_MESSAGE, collected_data=collected_data)
    )

    assert result["intent"] == THIRD_PARTY_GUARD_INTENT
    assert result["response_text"] == _SAFE_REPLY
    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS
    assert result["requires_handoff"] is False
    assert llm.understood is False
    kept = result["collected_data"]
    assert kept[HANDOFF_OFFER_KEY] is True
    assert kept.get("stage") == collected_data.get("stage")
    assert not any(key.startswith(("identification_", "new_patient_")) for key in kept)
    assert "30222333" not in str(llm.contexts[0].collected_data)
    assert "María" not in str(llm.contexts[0].collected_data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply", [LLMProviderError("boom"), "Hola! Listo, ya te lo cancelé al turno de tu familiar."]
)
async def test_falls_back_to_the_static_message(reply):
    node = create_resolve_interaction_node(_RecordingLLM(reply))

    result = await node(make_agent_state(user_message=_AUDIT_MESSAGE))

    assert result["response_text"] == THIRD_PARTY_STATIC_MESSAGE
    assert result["response_buttons"] == HANDOFF_OFFER_BUTTONS


def test_the_static_message_says_what_the_agent_can_do_and_carries_no_greeting():
    text = THIRD_PARTY_STATIC_MESSAGE.casefold()
    assert "propios" in text
    assert "dni" in text
    assert "asesor" in text
    assert not text.startswith(("hola", "buenas"))


@pytest.mark.asyncio
async def test_an_accepted_offer_reaches_the_handoff_like_the_buttons():
    node = create_resolve_interaction_node(_RecordingLLM(_SAFE_REPLY))
    first = await node(make_agent_state(user_message=_AUDIT_MESSAGE))

    second = await node(
        make_agent_state(user_message="dale", collected_data=first["collected_data"])
    )

    assert second["intent"] == "handoff"


@pytest.mark.asyncio
async def test_a_pending_confirmation_is_left_to_its_own_gate():
    llm = _RecordingLLM(_SAFE_REPLY)
    node = create_resolve_interaction_node(llm)

    result = await node(
        make_agent_state(
            user_message="mi mamá tiene turno",
            collected_data={"stage": "awaiting_confirmation"},
        )
    )

    assert result.get("intent") != THIRD_PARTY_GUARD_INTENT
    assert llm.understood is True


@pytest.mark.asyncio
async def test_a_patients_own_name_and_dni_pass_through_the_identification_stage():
    llm = _RecordingLLM(_SAFE_REPLY)
    node = create_resolve_interaction_node(llm)

    result = await node(
        make_agent_state(
            user_message="Pedro Cassera 30131313",
            collected_data={"stage": "awaiting_identification"},
        )
    )

    assert result["intent"] == "appointment"
    assert llm.contexts == []


def test_the_guard_reply_ends_the_graph_run():
    assert _route_after_resolve_interaction({"intent": THIRD_PARTY_GUARD_INTENT}) == END  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "message",
    [
        "anotala en la agenda",
        "pasame el turno",
        "quiero agendarle una alarma",
        "sacame un turno",
        "cambialo por favor",
        "Pedro Cassera 30131313",
    ],
)
def test_bare_clitic_verbs_are_not_a_third_party_claim(message):
    assert claims_to_act_for_someone_else(message) is False
