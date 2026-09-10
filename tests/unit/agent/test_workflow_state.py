from app.agent.workflow_state import invalidate_from


def _sample() -> dict[str, object]:
    return {
        "stage": "awaiting_slot_selection",
        "operation": "create_appointment",
        "patient": {"id": "p1", "dni": "30123456"},
        "identification_full_name": "Rosa Gómez",
        "identification_dni": "30123456",
        "chosen_specialty_id": "s1",
        "chosen_specialty_name": "General",
        "chosen_professional_id": "d1",
        "professional_options": ["doctor"],
        "available_slots": ["slot"],
        "pending_selected_slot": "slot",
        "professional_names": {"d1": "Dra. Uno"},
    }


def test_changing_slot_keeps_patient_specialty_and_professional():
    result = invalidate_from(_sample(), "slot")

    assert result["patient"] == {"id": "p1", "dni": "30123456"}
    assert result["chosen_specialty_id"] == "s1"
    assert result["chosen_professional_id"] == "d1"
    assert "available_slots" not in result
    assert "pending_selected_slot" not in result
    assert "stage" not in result


def test_changing_professional_keeps_patient_and_specialty_only():
    result = invalidate_from(_sample(), "professional")

    assert result["patient"] == {"id": "p1", "dni": "30123456"}
    assert result["chosen_specialty_id"] == "s1"
    assert "chosen_professional_id" not in result
    assert "available_slots" not in result
    assert result["identification_dni"] == "30123456"


def test_changing_specialty_keeps_identity_and_operation():
    result = invalidate_from(_sample(), "specialty")

    assert result["patient"] == {"id": "p1", "dni": "30123456"}
    assert result["operation"] == "create_appointment"
    assert result["identification_full_name"] == "Rosa Gómez"
    assert result["identification_dni"] == "30123456"
    assert "chosen_specialty_id" not in result
    assert "chosen_professional_id" not in result
    assert "available_slots" not in result
