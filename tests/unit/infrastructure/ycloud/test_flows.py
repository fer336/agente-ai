import json

import pytest

from app.infrastructure.ycloud.flows import (
    PATIENT_INTAKE_FLOW_SCREEN_ID,
    REGISTRATION_FLOW_SCREEN_ID,
    VERIFICATION_FLOW_SCREEN_ID,
    build_patient_intake_flow_json,
    build_registration_flow_json,
    build_verification_flow_json,
)


def _field_names(screen: dict) -> list[str]:
    return [child["name"] for child in screen["layout"]["children"] if child["type"] == "TextInput"]


def test_verification_flow_has_only_name_and_dni_fields():
    flow = json.loads(build_verification_flow_json())

    assert flow["screens"][0]["id"] == VERIFICATION_FLOW_SCREEN_ID
    assert flow["screens"][0]["terminal"] is True
    assert _field_names(flow["screens"][0]) == ["full_name", "dni"]


def test_registration_flow_never_asks_for_phone():
    flow = json.loads(build_registration_flow_json())

    assert flow["screens"][0]["id"] == REGISTRATION_FLOW_SCREEN_ID
    fields = _field_names(flow["screens"][0])
    assert "phone" not in fields
    assert "telefono" not in fields
    assert fields == ["full_name", "dni", "email", "obra_social"]


def test_registration_flow_marks_obra_social_as_optional():
    flow = json.loads(build_registration_flow_json())

    obra_social = next(
        child
        for child in flow["screens"][0]["layout"]["children"]
        if child.get("name") == "obra_social"
    )
    assert obra_social["required"] is False


def test_flow_without_image_has_no_image_component():
    flow = json.loads(build_verification_flow_json())

    types = [child["type"] for child in flow["screens"][0]["layout"]["children"]]
    assert "Image" not in types


def test_flow_with_image_includes_the_image_component_first():
    flow = json.loads(build_verification_flow_json(header_image_base64="data:image/png;base64,AAA"))

    first_child = flow["screens"][0]["layout"]["children"][0]
    assert first_child["type"] == "Image"
    assert first_child["src"] == "data:image/png;base64,AAA"


def test_oversized_image_is_rejected_before_building_the_flow():
    with pytest.raises(ValueError, match="exceeds"):
        build_verification_flow_json(header_image_base64="A" * 300_001)


def _intake_screen(header_image_base64: str | None = None) -> dict:
    flow = json.loads(build_patient_intake_flow_json(header_image_base64))
    assert flow["version"] == "6.2"
    assert len(flow["screens"]) == 1
    return flow["screens"][0]


def _named(children: list[dict], name: str) -> dict:
    return next(child for child in children if child.get("name") == name)


def test_intake_flow_is_a_single_terminal_screen():
    screen = _intake_screen()

    assert screen["id"] == PATIENT_INTAKE_FLOW_SCREEN_ID == "DATOS_PACIENTE"
    assert screen["terminal"] is True


def test_intake_flow_starts_with_the_required_patient_radio_group():
    children = _intake_screen()["layout"]["children"]

    radio = _named(children, "es_paciente")
    assert radio["type"] == "RadioButtonsGroup"
    assert radio["label"] == "¿Sos paciente del consultorio?"
    assert radio["required"] is True
    assert [option["id"] for option in radio["data-source"]] == ["si", "no"]


def test_intake_flow_always_shows_name_and_dni_with_digits_helper():
    children = _intake_screen()["layout"]["children"]

    assert _named(children, "full_name")["input-type"] == "text"
    dni = _named(children, "dni")
    assert dni["input-type"] == "number"
    assert dni["required"] is True
    assert "7" in dni["helper-text"] and "8" in dni["helper-text"]


def test_intake_flow_shows_email_and_obra_social_only_for_non_patients():
    children = _intake_screen()["layout"]["children"]

    conditional = next(child for child in children if child["type"] == "If")
    assert conditional["condition"] == "${form.es_paciente} == 'no'"
    nested = conditional["then"]
    assert _named(nested, "email")["required"] is True
    assert _named(nested, "email")["input-type"] == "email"
    assert _named(nested, "obra_social")["required"] is False
    top_level_names = {child.get("name") for child in children}
    assert "email" not in top_level_names
    assert "obra_social" not in top_level_names


def test_intake_flow_footer_completes_with_every_field_in_the_payload():
    children = _intake_screen()["layout"]["children"]

    footer = children[-1]
    assert footer["type"] == "Footer"
    action = footer["on-click-action"]
    assert action["name"] == "complete"
    assert action["payload"] == {
        "es_paciente": "${form.es_paciente}",
        "full_name": "${form.full_name}",
        "dni": "${form.dni}",
        "email": "${form.email}",
        "obra_social": "${form.obra_social}",
    }


def test_intake_flow_never_asks_for_phone():
    raw = build_patient_intake_flow_json()

    assert "phone" not in raw
    assert "telefono" not in raw


def test_intake_flow_with_image_puts_it_first_and_rejects_oversized():
    first = _intake_screen("data:image/png;base64,AAA")["layout"]["children"][0]
    assert first["type"] == "Image"

    with pytest.raises(ValueError, match="exceeds"):
        build_patient_intake_flow_json("A" * 300_001)
