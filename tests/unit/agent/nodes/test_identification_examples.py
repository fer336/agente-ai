"""The example shown when asking for the patient's data varies instead of being fixed."""

import re

import pytest

from app.agent.example_identity import EXAMPLE_FULL_NAMES
from app.agent.nodes.appointment import (
    _ask_dni_only_message,
    _ask_name_only_message,
    _dni_format_invalid_message,
    _identification_not_understood_message,
    _identification_prompt_text,
    _name_incomplete_message,
    _new_patient_rejected_message,
)
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation

_NAME = "Mariana Sosa"
_DNI = "27654321"


class _RecordingLLM(FakeLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[ResponseContext] = []

    async def generate_response(self, context: ResponseContext) -> str:
        self.calls.append(context)
        # An action claim is rejected by the node, which falls back to its static wording.
        return "Dale, ahí te lo cancelo entonces."


def _names_in(text: str) -> list[str]:
    return [name for name in EXAMPLE_FULL_NAMES if name in text]


@pytest.mark.parametrize(
    "message",
    [
        _identification_prompt_text(_NAME, _DNI),
        _identification_not_understood_message(_NAME, _DNI),
        _name_incomplete_message(_NAME, _DNI),
        _new_patient_rejected_message(_NAME, _DNI),
    ],
)
def test_name_and_dni_messages_embed_the_given_example(message):
    assert f"{_NAME}, {_DNI}" in message


def test_single_field_messages_embed_only_what_they_ask_for():
    assert _NAME in _ask_name_only_message(_NAME)
    assert _DNI in _ask_dni_only_message(_DNI)
    assert _DNI in _dni_format_invalid_message(_DNI)


def test_the_static_wording_is_otherwise_unchanged():
    assert _identification_prompt_text(_NAME, _DNI) == (
        "Para coordinar un turno necesito identificarte primero.\n\n"
        f"Escribime tu *nombre completo* y tu *DNI* (por ejemplo: {_NAME}, {_DNI})."
    )
    assert _ask_dni_only_message(_DNI) == (
        f"Gracias! Ahora decime tu *DNI* (7 u 8 dígitos), por ejemplo: {_DNI}."
    )


@pytest.mark.asyncio
async def test_the_identification_ask_instruction_and_fallback_share_a_catalog_example():
    llm = _RecordingLLM()
    node, _, _ = await make_node_and_conversation(llm_provider=llm)
    state = make_agent_state(
        user_message="quiero cancelar", collected_data={"operation_mention": "cancel"}
    )

    result = await node(state)

    instruction = str(llm.calls[0].collected_data["formato_requerido"])
    shown = re.search(r"ejemplo: (.+?), (\d{7,8})\.", instruction)
    assert shown is not None
    assert shown.group(1) in EXAMPLE_FULL_NAMES
    assert f"{shown.group(1)}, {shown.group(2)}" in result["response_text"]
    assert "Rosa Gómez, 30123456" not in instruction
    assert _names_in(result["response_text"])
