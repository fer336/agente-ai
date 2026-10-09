"""A wrong name or DNI is fixed alone: the bot asks only for that piece and keeps the other."""

import pytest

from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_IDENTIFICATION,
    STAGE_AWAITING_IDENTIFICATION_CONFIRMATION,
    STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE,
    STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
)
from app.domain.value_objects.menu_payloads import (
    IDENTIFICATION_CONFIRM_PAYLOAD,
    IDENTIFICATION_FIX_DNI_PAYLOAD,
    IDENTIFICATION_FIX_NAME_PAYLOAD,
    IDENTIFICATION_MODIFY_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    PATIENT_NOT_FOUND_RETRY_PAYLOAD,
)
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation
from tests.fixtures.seed_objects import make_patient

_IDENTIFYING = {"stage": STAGE_AWAITING_IDENTIFICATION, "operation": CREATE_APPOINTMENT_ACTION}


class _SpyGateway(FakePatientGateway):
    def __init__(self, patients=None) -> None:
        super().__init__(patients)
        self.lookups = 0

    async def find_patient(self, full_name, dni):
        self.lookups += 1
        return await super().find_patient(full_name, dni)


def _juan() -> _SpyGateway:
    return _SpyGateway([make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")])


async def _type(node, text, collected_data):
    return await node(make_agent_state(user_message=text, collected_data=collected_data))


async def _tap(node, payload, collected_data):
    return await node(make_agent_state(button_payload=payload, collected_data=collected_data))


async def _chooser(node, text="Juan Perez, 30999999"):
    shown = await _type(node, text, _IDENTIFYING)
    return await _tap(node, IDENTIFICATION_MODIFY_PAYLOAD, shown["collected_data"])


@pytest.mark.asyncio
async def test_modify_shows_the_chooser_and_keeps_both_pieces():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)

    result = await _chooser(node)

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30999999"
    assert data["operation"] == CREATE_APPOINTMENT_ACTION
    assert "qué dato" in result["response_text"].casefold()
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (IDENTIFICATION_FIX_NAME_PAYLOAD, "✏️ Nombre"),
        (IDENTIFICATION_FIX_DNI_PAYLOAD, "✏️ DNI"),
    ]
    assert all(len(b.title) <= 20 for b in result["response_buttons"])
    assert gateway.lookups == 0


@pytest.mark.asyncio
async def test_fixing_the_name_asks_only_for_the_name_and_keeps_the_dni():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _tap(node, IDENTIFICATION_FIX_NAME_PAYLOAD, chooser["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert not data.get("identification_full_name")
    assert data["identification_dni"] == "30999999"
    assert "nombre completo" in result["response_text"]
    assert "DNI" not in result["response_text"]
    assert result.get("response_buttons") is None


@pytest.mark.asyncio
async def test_the_new_name_leads_to_the_confirmation_again_with_the_old_dni():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    chooser = await _chooser(node, "Juan Perex, 30123456")
    asked = await _tap(node, IDENTIFICATION_FIX_NAME_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "Juan Perez", asked["collected_data"])

    data = again["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"
    assert "Juan Perez" in again["response_text"]
    assert gateway.lookups == 0
    done = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, data)
    assert done["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert gateway.lookups == 1


@pytest.mark.asyncio
async def test_fixing_the_dni_asks_only_for_the_dni_and_keeps_the_name():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _tap(node, IDENTIFICATION_FIX_DNI_PAYLOAD, chooser["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert data["identification_full_name"] == "Juan Perez"
    assert not data.get("identification_dni")
    assert "DNI" in result["response_text"]
    assert "nombre" not in result["response_text"].casefold()
    assert result.get("response_buttons") is None


@pytest.mark.asyncio
async def test_the_new_dni_leads_to_the_confirmation_again_with_the_old_name():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    chooser = await _chooser(node)
    asked = await _tap(node, IDENTIFICATION_FIX_DNI_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "30123456", asked["collected_data"])

    data = again["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"
    assert gateway.lookups == 0
    done = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, data)
    assert done["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


@pytest.mark.asyncio
async def test_an_invalid_new_dni_asks_again_only_for_the_dni_and_keeps_the_name():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)
    asked = await _tap(node, IDENTIFICATION_FIX_DNI_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "1234567890", asked["collected_data"])

    data = again["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert data["identification_full_name"] == "Juan Perez"
    assert not data.get("identification_dni")


@pytest.mark.asyncio
async def test_a_single_word_new_name_asks_again_only_for_the_name_and_keeps_the_dni():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)
    asked = await _tap(node, IDENTIFICATION_FIX_NAME_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "Juan", asked["collected_data"])

    data = again["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert data["identification_dni"] == "30999999"
    assert not data.get("identification_full_name")


@pytest.mark.asyncio
async def test_free_text_with_name_and_dni_at_the_chooser_is_a_correction():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    chooser = await _chooser(node)

    result = await _type(node, "Juan Perez, 30123456", chooser["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"
    assert gateway.lookups == 0


@pytest.mark.asyncio
async def test_free_text_with_only_a_valid_dni_at_the_chooser_keeps_the_name():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _type(node, "30123456", chooser["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["sí", "no sé", "Juan"])
async def test_unparseable_free_text_at_the_chooser_repeats_the_chooser(text):
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _type(node, text, chooser["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30999999"
    assert [b.id for b in result["response_buttons"]] == [
        IDENTIFICATION_FIX_NAME_PAYLOAD,
        IDENTIFICATION_FIX_DNI_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_a_stale_payload_at_the_chooser_repeats_the_chooser():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _tap(node, "SOME_OLD_PAYLOAD", chooser["collected_data"])

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert len(result["response_buttons"]) == 2


@pytest.mark.asyncio
async def test_a_main_menu_tap_at_the_chooser_resets_the_flow():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    chooser = await _chooser(node)

    result = await _tap(node, MENU_APPOINTMENT_PAYLOAD, chooser["collected_data"])

    assert result["collected_data"].get("stage") != STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert "identification_dni" not in result["collected_data"]


@pytest.mark.asyncio
async def test_an_incomplete_checkpoint_at_the_chooser_asks_for_the_missing_piece_only():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())

    result = await _tap(
        node,
        IDENTIFICATION_FIX_NAME_PAYLOAD,
        {**_IDENTIFYING, "stage": STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE},
    )

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION


@pytest.mark.asyncio
async def test_trying_other_data_after_not_found_shows_the_chooser_keeping_both_pieces():
    node, _, _ = await make_node_and_conversation(patient_gateway=_SpyGateway([]))
    shown = await _type(node, "Rosa Gomez, 30999888", _IDENTIFYING)
    not_found = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, shown["collected_data"])
    assert not_found["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE

    result = await _tap(node, PATIENT_NOT_FOUND_RETRY_PAYLOAD, not_found["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert data["identification_full_name"] == "Rosa Gomez"
    assert data["identification_dni"] == "30999888"
    assert data["not_found_retries"] == 1
    assert [b.id for b in result["response_buttons"]] == [
        IDENTIFICATION_FIX_NAME_PAYLOAD,
        IDENTIFICATION_FIX_DNI_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_a_wrong_dni_after_not_found_is_fixed_alone_and_the_patient_is_found():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    shown = await _type(node, "Juan Perez, 30999888", _IDENTIFYING)
    not_found = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, shown["collected_data"])
    chooser = await _tap(node, PATIENT_NOT_FOUND_RETRY_PAYLOAD, not_found["collected_data"])
    asked = await _tap(node, IDENTIFICATION_FIX_DNI_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "30123456", asked["collected_data"])
    found = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, again["collected_data"])

    assert again["collected_data"]["identification_full_name"] == "Juan Perez"
    assert found["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert found["collected_data"]["patient"]["dni"] == "30123456"


@pytest.mark.asyncio
async def test_missing_name_and_missing_dni_still_ask_only_for_that_piece():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())

    only_dni = await _type(node, "30123456", _IDENTIFYING)
    only_name = await _type(node, "Juan Perez", _IDENTIFYING)

    assert only_dni["collected_data"]["identification_dni"] == "30123456"
    assert "identification_missing_name" in only_dni["response_text"]
    assert only_name["collected_data"]["identification_full_name"] == "Juan Perez"
    assert "identification_missing_dni" in only_name["response_text"]
    assert only_name["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert only_dni["collected_data"].get("stage") == STAGE_AWAITING_IDENTIFICATION


@pytest.mark.asyncio
async def test_an_invalid_dni_still_asks_only_for_the_dni_and_keeps_the_name():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())

    result = await _type(node, "Juan Perez, 1234567890", _IDENTIFYING)

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION
    assert data["identification_full_name"] == "Juan Perez"
    assert not data.get("identification_dni")
