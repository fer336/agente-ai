import json

import pytest

from app.infrastructure.ycloud.flows import (
    REGISTRATION_FLOW_SCREEN_ID,
    VERIFICATION_FLOW_SCREEN_ID,
    build_registration_flow_json,
    build_verification_flow_json,
)


def _field_names(screen: dict) -> list[str]:
    return [
        child["name"]
        for child in screen["layout"]["children"]
        if child["type"] == "TextInput"
    ]


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
