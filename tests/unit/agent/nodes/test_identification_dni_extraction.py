import pytest

from app.agent.nodes.appointment import _extract_identification_pieces
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider


@pytest.mark.asyncio
async def test_a_single_dni_keeps_working_with_its_name():
    name, dni = await _extract_identification_pieces(FakeLLMProvider(), "Rosa Gómez, 30123456")

    assert (name, dni) == ("Rosa Gómez", "30123456")


@pytest.mark.asyncio
async def test_the_last_number_wins_when_the_patient_corrects_the_dni():
    # Live case: name, a DNI, then a typo correction, grouped into one turn.
    name, dni = await _extract_identification_pieces(
        FakeLLMProvider(), "Pedro cassera\n30231313\n30131313"
    )

    assert dni == "30131313"
    assert name == "Pedro cassera"


@pytest.mark.asyncio
async def test_the_name_does_not_keep_the_discarded_earlier_number():
    name, _ = await _extract_identification_pieces(
        FakeLLMProvider(), "30231313 Pedro cassera 30131313"
    )

    assert name == "Pedro cassera"


@pytest.mark.asyncio
async def test_a_phone_number_after_the_dni_is_not_taken_for_the_dni():
    _, dni = await _extract_identification_pieces(
        FakeLLMProvider(), "Rosa Gómez 30123456 cel 1155551234"
    )

    assert dni == "30123456"


@pytest.mark.asyncio
async def test_an_over_long_number_is_still_extracted_so_the_invalid_dni_path_runs():
    name, dni = await _extract_identification_pieces(
        FakeLLMProvider(), "Ferdinando perez, 3012121212"
    )

    assert dni == "3012121212"
    assert name == "Ferdinando perez"


@pytest.mark.asyncio
async def test_a_message_without_digits_has_no_dni():
    name, dni = await _extract_identification_pieces(FakeLLMProvider(), "Rosa Gómez")

    assert (name, dni) == ("Rosa Gómez", None)
