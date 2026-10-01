import pytest

from app.agent.clinic_topics import special_insurance_message, special_insurance_text_is_valid
from app.agent.nodes.agreement import create_agreement_node
from app.domain.repositories.llm_provider import ResponseContext
from app.infrastructure.llm.exceptions import LLMProviderError
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_confirms_when_the_agreement_is_configured():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="Galeno")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(make_agent_state(user_message="¿Trabajan con Galeno?"))

    assert result["response_text"] == "[fake-response for intent=agreement_found] con Galeno"
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_reports_not_found_when_no_configured_agreement_matches():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(make_agent_state(user_message="¿Trabajan con Swiss Medical?"))

    assert result["response_text"] == "[fake-response for intent=agreement_not_found]"


@pytest.mark.asyncio
async def test_derives_to_admin_for_coverage_amount_questions():
    # This exact wording is a PRD.md §20 requirement, not a stylistic
    # default — it deliberately stays hardcoded (never LLM-generated).
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="¿Cuánto me cubre OSDE en una corona?")
    )

    assert result["response_text"] == (
        "Esta consulta necesita ser revisada por administración.\n"
        "Querés que te comunique con ellos?"
    )


@pytest.mark.asyncio
async def test_never_invents_a_match_for_an_unconfigured_agreement_percentage_question():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(
        make_agent_state(user_message="¿Qué porcentaje cubre Swiss Medical?")
    )

    assert result["response_text"] == "[fake-response for intent=agreement_not_found]"


_INSURANCE_CASES = [
    ("¿Atienden OSDE?", "OSDE"),
    ("tengo osde 210", "OSDE"),
    ("Tengo Medifé", "Medifé"),
    ("tengo medife", "Medifé"),
    ("¿Trabajan con William Hope?", "William Hope"),
]


class _RecordingLLM(FakeLLMProvider):
    """Returns scripted texts in order (the last one repeats) and records every context."""

    def __init__(self, *texts: str, error: bool = False) -> None:
        super().__init__()
        self._texts = list(texts)
        self._error = error
        self.contexts: list[ResponseContext] = []

    async def generate_response(self, context: ResponseContext) -> str:
        self.contexts.append(context)
        if self._error:
            raise LLMProviderError("boom")
        index = min(len(self.contexts) - 1, len(self._texts) - 1)
        return self._texts[index]


_PARAPHRASE = (
    "Con {name} podés reservar una primera consulta: un profesional te hace un diagnóstico "
    "integral y personalizado, y {name} la cubre. Si hace falta otro tratamiento, te derivan "
    "al especialista que corresponda."
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "display_name"), _INSURANCE_CASES)
async def test_special_insurances_with_the_fake_llm_name_the_insurance_and_keep_the_facts(
    message: str, display_name: str
):
    # Even when the clinic's agreements list has no such entry.
    gateway = make_agreement_gateway(agreements=[make_agreement(name="Galeno")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(make_agent_state(user_message=message))

    assert display_name in result["response_text"]
    assert special_insurance_text_is_valid(result["response_text"], display_name)
    assert result["response_text"] != special_insurance_message(display_name)
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_the_fake_llm_text_varies_with_the_insurance():
    node = create_agreement_node(make_agreement_gateway(agreements=[]), FakeLLMProvider())

    osde = await node(make_agent_state(user_message="tengo osde"))
    medife = await node(make_agent_state(user_message="tengo medifé"))

    assert osde["response_text"] != medife["response_text"]


@pytest.mark.asyncio
async def test_a_valid_llm_paraphrase_is_sent_instead_of_the_fixed_text():
    llm = _RecordingLLM(_PARAPHRASE.format(name="Medifé"))
    node = create_agreement_node(make_agreement_gateway(agreements=[]), llm)

    result = await node(make_agent_state(user_message="tengo medifé"))

    assert result["response_text"] == _PARAPHRASE.format(name="Medifé")
    context = llm.contexts[0]
    assert context.intent == "special_insurance"
    assert context.temperature is not None and context.temperature >= 0.8
    assert context.collected_data["seguro"] == "Medifé"
    assert special_insurance_message("Medifé") in str(context.collected_data["instruccion"])


@pytest.mark.asyncio
async def test_invented_coverage_figures_fall_back_to_the_fixed_clinic_text():
    llm = _RecordingLLM("Con OSDE tenés una primera visita y cubre el 100%.")
    node = create_agreement_node(make_agreement_gateway(agreements=[]), llm)

    result = await node(make_agent_state(user_message="tengo osde"))

    assert result["response_text"] == special_insurance_message("OSDE")


@pytest.mark.asyncio
async def test_a_text_missing_a_fact_falls_back_to_the_fixed_clinic_text():
    llm = _RecordingLLM("¡Claro, con OSDE trabajamos! Agendá cuando quieras.")
    node = create_agreement_node(make_agreement_gateway(agreements=[]), llm)

    result = await node(make_agent_state(user_message="tengo osde"))

    assert result["response_text"] == special_insurance_message("OSDE")


@pytest.mark.asyncio
async def test_an_llm_error_falls_back_to_the_fixed_clinic_text():
    node = create_agreement_node(make_agreement_gateway(agreements=[]), _RecordingLLM(error=True))

    result = await node(make_agent_state(user_message="tengo william hope"))

    assert result["response_text"] == special_insurance_message("William Hope")


@pytest.mark.asyncio
async def test_a_second_ask_receives_the_earlier_answer_to_avoid_repeating_it():
    llm = _RecordingLLM(_PARAPHRASE.format(name="Medifé"), _PARAPHRASE.format(name="OSDE"))
    node = create_agreement_node(make_agreement_gateway(agreements=[]), llm)
    first = await node(make_agent_state(user_message="tengo medifé"))
    history = [
        {"role": "user", "content": "tengo medifé"},
        {"role": "assistant", "content": first["response_text"]},
    ]

    second = await node(make_agent_state(user_message="y con osde?", recent_messages=history))

    assert "OSDE" in second["response_text"]
    assert second["response_text"] != first["response_text"]
    assert llm.contexts[1].recent_messages == history
    assert llm.contexts[1].conversation_started is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["¿Cuánto cubre OSDE?", "qué porcentaje cubre medife", "¿Cuánto me cubre William Hope?"],
)
async def test_coverage_questions_about_special_insurances_still_derive_to_admin(message: str):
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    node = create_agreement_node(gateway, FakeLLMProvider())

    result = await node(make_agent_state(user_message=message))

    assert result["response_text"] == (
        "Esta consulta necesita ser revisada por administración.\n"
        "Querés que te comunique con ellos?"
    )
