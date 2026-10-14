import base64
import json

import pytest

from app.infrastructure.ycloud.flows import (
    PATIENT_INTAKE_FLOW_SCREEN_ID,
    REGISTRATION_FLOW_SCREEN_ID,
    VERIFICATION_FLOW_SCREEN_ID,
    build_patient_intake_flow_json,
    build_registration_flow_json,
    build_verification_flow_json,
    load_flow_header_image_base64,
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


def _intake_screen(
    header_image_base64: str | None = None, agreement_names: list[str] | None = None
) -> dict:
    flow = json.loads(build_patient_intake_flow_json(header_image_base64, agreement_names or []))
    assert flow["version"] == "6.2"
    assert len(flow["screens"]) == 1
    return flow["screens"][0]


def _named(children: list[dict], name: str) -> dict:
    return next(child for child in children if child.get("name") == name)


def _form_children(screen: dict) -> list[dict]:
    layout = screen["layout"]
    assert layout["type"] == "SingleColumnLayout"
    (form,) = layout["children"]
    assert form["type"] == "Form"
    assert form["name"] == "form"
    return form["children"]


def test_intake_flow_is_a_single_terminal_screen():
    screen = _intake_screen()

    assert screen["id"] == PATIENT_INTAKE_FLOW_SCREEN_ID == "DATOS_PACIENTE"
    assert screen["terminal"] is True


def test_intake_flow_starts_with_the_required_patient_radio_group():
    children = _form_children(_intake_screen())

    radio = _named(children, "es_paciente")
    assert radio["type"] == "RadioButtonsGroup"
    assert radio["label"] == "¿Sos paciente del consultorio?"
    assert radio["required"] is True
    assert [option["id"] for option in radio["data-source"]] == ["si", "no"]


def test_intake_flow_always_shows_name_and_dni_with_digits_helper():
    children = _form_children(_intake_screen())

    assert _named(children, "full_name")["input-type"] == "text"
    dni = _named(children, "dni")
    assert dni["input-type"] == "number"
    assert dni["required"] is True
    assert "7" in dni["helper-text"] and "8" in dni["helper-text"]


def _new_patient_block(children: list[dict]) -> list[dict]:
    conditional = next(child for child in children if child["type"] == "If")
    assert conditional["condition"] == "${form.es_paciente} == 'no'"
    return conditional["then"]


def test_intake_flow_shows_email_and_obra_social_only_for_non_patients():
    children = _form_children(_intake_screen())

    nested = _new_patient_block(children)
    assert _named(nested, "email")["required"] is True
    assert _named(nested, "email")["input-type"] == "email"
    obra_social = _named(nested, "obra_social")
    assert obra_social["type"] == "Dropdown"
    assert obra_social["required"] is True
    top_level_names = {child.get("name") for child in children}
    assert {"email", "obra_social", "plan"}.isdisjoint(top_level_names)


def test_obra_social_dropdown_always_offers_particular_and_the_given_agreements():
    children = _form_children(_intake_screen(agreement_names=["OSDE", "Swiss Medical", "Galeno"]))

    options = _named(_new_patient_block(children), "obra_social")["data-source"]
    assert {"id": "particular", "title": "Particular"} in options
    # The id is the agreement name itself so the backend can look it up as-is.
    assert {"id": "OSDE", "title": "OSDE"} in options
    assert [option["id"] for option in options] == [
        "particular",
        "OSDE",
        "Swiss Medical",
        "Galeno",
    ]


def test_obra_social_dropdown_without_agreements_still_has_particular():
    children = _form_children(_intake_screen())

    options = _named(_new_patient_block(children), "obra_social")["data-source"]
    assert options == [{"id": "particular", "title": "Particular"}]


def test_obra_social_dropdown_dedupes_skips_empty_and_replaces_particular():
    children = _form_children(
        _intake_screen(
            agreement_names=["OSDE", "  osde ", "", "   ", "Particular", "PARTICULAR", "Galeno"]
        )
    )

    options = _named(_new_patient_block(children), "obra_social")["data-source"]
    assert [option["id"] for option in options] == ["particular", "OSDE", "Galeno"]


def test_obra_social_dropdown_truncates_long_titles_but_keeps_the_full_id():
    long_name = "Obra Social del Personal de la Industria Metalúrgica Argentina"

    children = _form_children(_intake_screen(agreement_names=[long_name, "Otra"]))

    options = _named(_new_patient_block(children), "obra_social")["data-source"]
    long_option = next(option for option in options if option["id"] == long_name)
    assert len(long_option["title"]) <= 30
    assert long_option["title"].endswith("…")


def test_obra_social_dropdown_is_capped_at_200_options():
    names = [f"Convenio {n}" for n in range(300)]

    children = _form_children(_intake_screen(agreement_names=names))

    options = _named(_new_patient_block(children), "obra_social")["data-source"]
    assert len(options) == 200
    assert options[0]["id"] == "particular"
    assert len({option["id"] for option in options}) == 200


def test_obra_social_dropdown_label_fits_meta_limit():
    children = _form_children(_intake_screen())

    label = _named(_new_patient_block(children), "obra_social")["label"]
    assert len(label) <= 20


def test_plan_is_optional_and_hidden_until_a_non_particular_obra_social_is_chosen():
    children = _form_children(_intake_screen())

    nested = _new_patient_block(children)
    plan_if = next(child for child in nested if child["type"] == "If")
    assert (
        plan_if["condition"] == "${form.obra_social} != '' && ${form.obra_social} != 'particular'"
    )
    plan = _named(plan_if["then"], "plan")
    assert plan["type"] == "TextInput"
    assert plan["required"] is False
    assert "plan" not in {child.get("name") for child in nested}


def test_intake_flow_footer_completes_with_every_field_in_the_payload():
    children = _form_children(_intake_screen())

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
        "plan": "${form.plan}",
    }


def test_header_image_alt_text_names_the_clinic():
    first = _form_children(_intake_screen("AAA"))[0]

    assert first["alt-text"] == "Smiling Dental Studio"


def test_header_logo_loader_returns_base64_png_under_the_size_limit():
    encoded = load_flow_header_image_base64()

    assert base64.b64decode(encoded)[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(encoded) <= 300_000
    # Accepted by the builder's own size guard.
    build_patient_intake_flow_json(encoded)


def test_intake_flow_never_asks_for_phone():
    raw = build_patient_intake_flow_json()

    assert "phone" not in raw
    assert "telefono" not in raw


def test_intake_flow_with_image_puts_it_first_and_rejects_oversized():
    first = _form_children(_intake_screen("data:image/png;base64,AAA"))[0]
    assert first["type"] == "Image"

    with pytest.raises(ValueError, match="exceeds"):
        build_patient_intake_flow_json("A" * 300_001)
