from datetime import UTC, datetime, timedelta

import pytest

from app.agent.nodes.search_availability import create_search_availability_node
from app.agent.state import AgentState
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


def _state(**overrides: object) -> AgentState:
    base: AgentState = {
        "conversation_id": "conv-1",
        "message_ids": ["msg-1"],
        "user_message": "Necesito un turno",
        "intent": "schedule_appointment",
        "collected_data": {},
        "missing_fields": [],
        "pending_action_id": None,
        "response_text": None,
        "requires_handoff": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _future_slot(id_: str = "slot-1") -> AppointmentSlot:
    now = datetime.now(UTC)
    return AppointmentSlot(
        id=id_,
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(now + timedelta(days=1), now + timedelta(days=1, hours=1)),
    )


@pytest.mark.asyncio
async def test_node_writes_gateway_slots_into_collected_data():
    slot = _future_slot()
    gateway = FakeDentalinkGateway(available_slots=[slot])
    node = create_search_availability_node(gateway)

    result = await node(_state())

    assert result["collected_data"]["available_slots"] == [slot]


@pytest.mark.asyncio
async def test_node_returns_empty_slots_when_gateway_has_no_availability():
    gateway = FakeDentalinkGateway(available_slots=[])
    node = create_search_availability_node(gateway)

    result = await node(_state())

    assert result["collected_data"]["available_slots"] == []


@pytest.mark.asyncio
async def test_node_preserves_existing_collected_data_keys():
    gateway = FakeDentalinkGateway(available_slots=[])
    node = create_search_availability_node(gateway)
    state = _state(collected_data={"patient_name": "Jane"})

    result = await node(state)

    assert result["collected_data"]["patient_name"] == "Jane"
    assert result["collected_data"]["available_slots"] == []
