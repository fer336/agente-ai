import pytest

from app.domain.repositories.llm_provider import (
    ExtractionResult,
    IntentResult,
    LLMProvider,
    ResponseContext,
)
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.gateways import make_llm_provider


@pytest.mark.asyncio
async def test_classify_intent_recognizes_appointment_keyword():
    provider = make_llm_provider()

    result = await provider.classify_intent("Quiero pedir un turno", context={})

    assert result == IntentResult(intent="appointment", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_intent_recognizes_insurance_keyword():
    provider = make_llm_provider()

    result = await provider.classify_intent("¿Trabajan con OSDE?", context={})

    assert result == IntentResult(intent="insurance", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_intent_recognizes_specialty_keyword():
    provider = make_llm_provider()

    result = await provider.classify_intent("¿Qué especialidades tienen?", context={})

    assert result == IntentResult(intent="specialties", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_intent_recognizes_handoff_keyword():
    provider = make_llm_provider()

    result = await provider.classify_intent("Voy a llegar tarde", context={})

    assert result == IntentResult(intent="handoff", confidence=0.9)


@pytest.mark.asyncio
async def test_classify_intent_prioritizes_handoff_over_appointment_keywords():
    # PRD.md §22: "No se intentará modificar automáticamente un turno porque
    # el paciente indique que llegará tarde. Ese caso siempre se deriva."
    provider = make_llm_provider()

    result = await provider.classify_intent(
        "Voy a llegar tarde a mi turno de hoy", context={}
    )

    assert result.intent == "handoff"


@pytest.mark.asyncio
async def test_classify_intent_returns_unknown_for_unrecognized_message():
    provider = make_llm_provider()

    result = await provider.classify_intent("Hola, buen día", context={})

    assert result == IntentResult(intent="unknown", confidence=0.0)


@pytest.mark.asyncio
async def test_extract_information_reports_all_requested_fields_as_missing():
    provider = make_llm_provider()

    result = await provider.extract_information(
        "Quiero un turno", required_fields=["specialty", "date"]
    )

    assert result == ExtractionResult(fields={}, missing_fields=["specialty", "date"])


@pytest.mark.asyncio
async def test_extract_information_accepts_a_plausible_full_name():
    provider = make_llm_provider()

    result = await provider.extract_information(
        "Pedro Cassera", required_fields=["nombre_completo"]
    )

    assert result == ExtractionResult(
        fields={"nombre_completo": "Pedro Cassera"}, missing_fields=[]
    )


@pytest.mark.asyncio
async def test_extract_information_rejects_casual_chatter_as_a_full_name():
    # Live bug this fake must reproduce for tests: "Bien vos?" is not a name.
    provider = make_llm_provider()

    result = await provider.extract_information("Bien vos?", required_fields=["nombre_completo"])

    assert result == ExtractionResult(fields={}, missing_fields=["nombre_completo"])


@pytest.mark.asyncio
async def test_extract_information_finds_a_dni_digit_run():
    provider = make_llm_provider()

    result = await provider.extract_information(
        "mi dni es 30123456", required_fields=["dni"]
    )

    assert result == ExtractionResult(fields={"dni": "30123456"}, missing_fields=[])


@pytest.mark.asyncio
async def test_generate_response_includes_the_intent_from_context():
    provider = make_llm_provider()
    context = ResponseContext(conversation_id="conv-1", intent="appointment", collected_data={})

    response = await provider.generate_response(context)

    assert response == "[fake-response for intent=appointment]"


def test_fake_llm_provider_satisfies_llm_provider_protocol():
    assert isinstance(FakeLLMProvider(), LLMProvider)


@pytest.mark.asyncio
async def test_understand_reads_a_view_question_as_view_not_create():
    # Regression, seen live: "Qué turnos tengo?" contains "turno" too, so
    # without a dedicated check this was read as operation_mention="create"
    # (the generic appointment-keyword fallback) instead of "view".
    provider = make_llm_provider()

    result = await provider.understand("Que turnos tengo?", context={})

    assert result.operation_mention == "view"


@pytest.mark.asyncio
async def test_understand_still_reads_a_plain_booking_request_as_create():
    provider = make_llm_provider()

    result = await provider.understand("Quiero sacar un turno", context={})

    assert result.operation_mention == "create"


@pytest.mark.asyncio
async def test_understand_reads_a_cancel_request_as_cancel():
    # T3(b) of the fallback-menu-buttons change: cancel/reschedule/book are
    # meant to reach the appointment flow from free text alone (no dedicated
    # buttons) — this pins the keyword layer for the exact phrasing PRD.md's
    # brief calls out. "mi turno" alone would otherwise match
    # `_VIEW_APPOINTMENT_KEYWORDS`, but the `cancelar`/`anular` check runs
    # first in `understand()`'s if/elif chain.
    provider = make_llm_provider()

    result = await provider.understand("quiero cancelar mi turno", context={})

    assert result.operation_mention == "cancel"


@pytest.mark.asyncio
async def test_classify_intent_never_returns_location():
    # T4 R3-fake-classify-intent-diverges-from-real-labels: the real
    # provider's `_INTENT_LABELS` (the narrow set `classify_intent` is
    # validated against) never includes "location" — only its separate,
    # richer `_UNDERSTANDING_LABELS` does (T3's own change). The fake must
    # match: "location" is an `understand()`-only label, never something
    # `classify_intent` can return, so a caller of the narrow classifier
    # (the eval suite) never gets a label the real provider would reject.
    provider = make_llm_provider()

    result = await provider.classify_intent("cómo hago para llegar", context={})

    assert result.intent != "location"


@pytest.mark.asyncio
async def test_understand_still_recognizes_location_after_classify_intent_narrowing():
    # Companion to the above: moving "location" out of `classify_intent`
    # must not also remove it from `understand()`, which is the actual
    # label parity T3 added.
    provider = make_llm_provider()

    result = await provider.understand("cómo hago para llegar", context={})

    assert result.intent == "location"


@pytest.mark.asyncio
async def test_understand_reads_a_reschedule_request_as_reschedule():
    # T3(b): same regression-coverage gap as the cancel case above, for
    # "reagendar" — this phrasing has no "turno"/"cita" in it at all, so
    # `classify_intent` alone reads it as low-confidence "unknown"; only
    # `operation_mention` carries the real signal (see
    # `resolve_interaction.py`'s own low-confidence operation-mention
    # carve-out).
    provider = make_llm_provider()

    result = await provider.understand("quiero reagendar", context={})

    assert result.operation_mention == "reschedule"
