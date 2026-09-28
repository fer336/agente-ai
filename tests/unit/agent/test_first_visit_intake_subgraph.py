import pytest

from app.agent.first_visit_intake_subgraph import (
    FIRST_VISIT_CONFIRM_PAYLOAD,
    FIRST_VISIT_EXISTING_PATIENT_PAYLOAD,
    FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
    FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
    build_first_visit_intake_graph,
)


@pytest.mark.asyncio
async def test_existing_patient_skips_intake_to_specialties():
    result = await build_first_visit_intake_graph().ainvoke(
        {"button_payload": FIRST_VISIT_EXISTING_PATIENT_PAYLOAD}
    )

    assert result["next_action"] == "specialties"
    assert result["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_new_patient_cannot_confirm_until_every_required_field_is_collected():
    graph = build_first_visit_intake_graph()
    state = await graph.ainvoke({"button_payload": FIRST_VISIT_CONFIRM_PAYLOAD})
    assert state["stage"] == "collect"
    assert "nombre y apellido" in state["response_text"].casefold()

    for value in ("Ana Pérez", "30123456", "+54 9 11 1234 5678"):
        state = await graph.ainvoke({**state, "user_message": value, "button_payload": None})

    assert state["stage"] == "collect"
    assert "obra social y plan" in state["response_text"].casefold()
    assert state["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_review_modification_returns_to_review_before_persistence():
    graph = build_first_visit_intake_graph()
    state = await graph.ainvoke({"button_payload": FIRST_VISIT_CONFIRM_PAYLOAD})
    for value in ("Ana Pérez", "30123456", "+54 9 11 1234 5678", "OSDE 210"):
        state = await graph.ainvoke({**state, "user_message": value, "button_payload": None})

    assert state["stage"] == "review"
    state = await graph.ainvoke({**state, "button_payload": FIRST_VISIT_REVIEW_MODIFY_PAYLOAD})
    state = await graph.ainvoke({**state, "user_message": "teléfono", "button_payload": None})
    state = await graph.ainvoke(
        {**state, "user_message": "+54 9 11 9876 5432", "button_payload": None}
    )

    assert state["stage"] == "review"
    assert state["details"]["phone"] == "+54 9 11 9876 5432"
    confirmed = await graph.ainvoke({**state, "button_payload": FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD})
    assert confirmed["next_action"] == "persist"
    assert confirmed["ready_to_persist"] is True
