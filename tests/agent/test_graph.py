from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import SEARCH_AVAILABILITY_NODE, build_graph, compile_graph
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


def _future_slot(id_: str = "slot-1") -> AppointmentSlot:
    now = datetime.now(UTC)
    return AppointmentSlot(
        id=id_,
        professional_id="prof-1",
        specialty_id="cleaning",
        time_range=DateTimeRange(now + timedelta(days=1), now + timedelta(days=1, hours=1)),
    )


def _initial_state(conversation_id: str) -> dict[str, object]:
    return {
        "conversation_id": conversation_id,
        "message_ids": ["msg-1"],
        "user_message": "Necesito un turno",
        "intent": "schedule_appointment",
        "collected_data": {},
        "missing_fields": [],
        "pending_action_id": None,
        "response_text": None,
        "requires_handoff": False,
    }


def test_build_graph_wires_the_search_availability_node():
    graph = build_graph(FakeDentalinkGateway())

    assert SEARCH_AVAILABILITY_NODE in graph.nodes


@pytest.mark.asyncio
async def test_compiled_graph_invocation_calls_the_node_and_populates_state():
    slot = _future_slot()
    gateway = FakeDentalinkGateway(available_slots=[slot])
    compiled = compile_graph(gateway)

    result = await compiled.ainvoke(_initial_state("conv-1"))

    assert result["collected_data"]["available_slots"] == [slot]


@pytest.mark.asyncio
async def test_compiled_graph_persists_and_restores_state_via_checkpointer_by_thread_id():
    gateway = FakeDentalinkGateway(available_slots=[_future_slot()])
    checkpointer = MemorySaver()
    compiled = compile_graph(gateway, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "conv-checkpoint-1"}}

    await compiled.ainvoke(_initial_state("conv-checkpoint-1"), config=config)
    restored = await compiled.aget_state(config)

    assert restored.values["conversation_id"] == "conv-checkpoint-1"
    assert len(restored.values["collected_data"]["available_slots"]) == 1
