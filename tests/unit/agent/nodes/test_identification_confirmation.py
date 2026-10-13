"""The typed name and DNI are echoed back for confirmation before any Dentalink lookup."""

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
    IDENTIFICATION_MODIFY_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
)
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.appointment_node import make_node_and_conversation
from tests.fixtures.seed_objects import make_patient


class _SpyPatientGateway(FakePatientGateway):
    def __init__(self, patients=None) -> None:
        super().__init__(patients)
        self.lookups: list[str] = []

    async def find_patient(self, full_name, dni):
        self.lookups.append(f"find_patient:{dni}")
        return await super().find_patient(full_name, dni)

    async def find_patient_by_dni(self, dni):
        self.lookups.append(f"find_patient_by_dni:{dni}")
        return await super().find_patient_by_dni(dni)


def _juan() -> _SpyPatientGateway:
    return _SpyPatientGateway([make_patient(id_="pat-1", full_name="Juan Perez", dni="30123456")])


async def _type(node, text, collected_data):
    return await node(make_agent_state(user_message=text, collected_data=collected_data))


async def _tap(node, payload, collected_data):
    return await node(make_agent_state(button_payload=payload, collected_data=collected_data))


_IDENTIFYING = {"stage": STAGE_AWAITING_IDENTIFICATION, "operation": CREATE_APPOINTMENT_ACTION}


@pytest.mark.asyncio
async def test_typed_name_and_dni_show_the_confirmation_without_any_lookup():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)

    result = await _type(node, "Juan Perez, 30123456", _IDENTIFYING)

    assert gateway.lookups == []
    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"
    assert "Juan Perez" in result["response_text"]
    assert "30123456" in result["response_text"]
    assert [(b.id, b.title) for b in result["response_buttons"]] == [
        (IDENTIFICATION_CONFIRM_PAYLOAD, "✅ Confirmar"),
        (IDENTIFICATION_MODIFY_PAYLOAD, "✏️ Modificar"),
    ]
    assert all(len(b.title) <= 20 for b in result["response_buttons"])
    assert result["requires_handoff"] is False


@pytest.mark.asyncio
async def test_confirming_a_registered_patient_runs_the_lookup_and_continues_the_flow():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Juan Perez, 30123456", _IDENTIFYING)

    result = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, shown["collected_data"])

    assert gateway.lookups
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
    assert result["collected_data"]["patient"]["dni"] == "30123456"


@pytest.mark.asyncio
async def test_confirming_an_unknown_patient_offers_the_existing_not_found_choice():
    gateway = _SpyPatientGateway([])
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Rosa Gomez, 30999888", _IDENTIFYING)

    result = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, shown["collected_data"])

    assert result["collected_data"]["stage"] == STAGE_AWAITING_PATIENT_NOT_FOUND_CHOICE
    assert len(result["response_buttons"]) == 3


@pytest.mark.asyncio
async def test_modify_asks_which_piece_to_fix_and_keeps_both():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Juan Perez, 30123456", _IDENTIFYING)

    result = await _tap(node, IDENTIFICATION_MODIFY_PAYLOAD, shown["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_FIELD_CHOICE
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30123456"
    assert data["operation"] == CREATE_APPOINTMENT_ACTION
    assert len(result["response_buttons"]) == 2
    assert gateway.lookups == []


@pytest.mark.asyncio
async def test_modify_then_fix_the_dni_shows_the_confirmation_again_until_confirmed():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Juan Perez, 30999999", _IDENTIFYING)
    chooser = await _tap(node, IDENTIFICATION_MODIFY_PAYLOAD, shown["collected_data"])
    asked = await _tap(node, IDENTIFICATION_FIX_DNI_PAYLOAD, chooser["collected_data"])

    again = await _type(node, "30123456", asked["collected_data"])

    assert again["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert "30123456" in again["response_text"]
    assert "30999999" not in again["response_text"]
    assert gateway.lookups == []
    done = await _tap(node, IDENTIFICATION_CONFIRM_PAYLOAD, again["collected_data"])
    assert done["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION


@pytest.mark.asyncio
async def test_free_text_with_a_parseable_name_and_dni_replaces_the_data_and_asks_again():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Juan Perez, 30999999", _IDENTIFYING)

    result = await _type(node, "Juan Perez, 30123456", shown["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_dni"] == "30123456"
    assert "30123456" in result["response_text"]
    assert len(result["response_buttons"]) == 2
    assert gateway.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["sí", "no sé", "30123456", "Juan"])
async def test_unparseable_free_text_repeats_the_buttons_and_keeps_the_data(text):
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    shown = await _type(node, "Juan Perez, 30999999", _IDENTIFYING)

    result = await _type(node, text, shown["collected_data"])

    data = result["collected_data"]
    assert data["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert data["identification_full_name"] == "Juan Perez"
    assert data["identification_dni"] == "30999999"
    assert [b.id for b in result["response_buttons"]] == [
        IDENTIFICATION_CONFIRM_PAYLOAD,
        IDENTIFICATION_MODIFY_PAYLOAD,
    ]
    assert gateway.lookups == []


@pytest.mark.asyncio
async def test_a_grouped_message_with_two_dnis_shows_the_confirmation_so_it_can_be_fixed():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)

    result = await _type(node, "Pedro Cassera\n30231313\n30131313", _IDENTIFYING)

    assert gateway.lookups == []
    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert "Pedro Cassera" in result["response_text"]
    assert any(b.id == IDENTIFICATION_MODIFY_PAYLOAD for b in result["response_buttons"])


@pytest.mark.asyncio
async def test_a_main_menu_tap_at_the_confirmation_resets_the_flow():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    shown = await _type(node, "Juan Perez, 30123456", _IDENTIFYING)

    result = await _tap(node, MENU_APPOINTMENT_PAYLOAD, shown["collected_data"])

    assert result["collected_data"].get("stage") != STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert "identification_dni" not in result["collected_data"]


@pytest.mark.asyncio
async def test_a_stale_payload_at_the_confirmation_repeats_the_buttons():
    node, _, _ = await make_node_and_conversation(patient_gateway=_juan())
    shown = await _type(node, "Juan Perez, 30123456", _IDENTIFYING)

    result = await _tap(node, "SOME_OLD_PAYLOAD", shown["collected_data"])

    assert result["collected_data"]["stage"] == STAGE_AWAITING_IDENTIFICATION_CONFIRMATION
    assert len(result["response_buttons"]) == 2


@pytest.mark.asyncio
async def test_an_already_identified_patient_is_not_asked_to_confirm_again():
    gateway = _juan()
    node, _, _ = await make_node_and_conversation(patient_gateway=gateway)
    identified = {"id": "pat-1", "full_name": "Juan Perez", "dni": "30123456"}

    result = await _type(
        node,
        "Juan Perez, 30123456",
        {**_IDENTIFYING, "patient": identified},
    )

    assert gateway.lookups
    assert result["collected_data"]["stage"] == STAGE_AWAITING_SPECIALTY_SELECTION
