"""Guardrail tests for the shared Dentalink `q=` filter builder.

Mirrors the injection tests that already covered `patient_gateway`'s own
private copy of this helper, now that both gateways share one
implementation.
"""

import json

import pytest

from app.infrastructure.dentalink.query_filter import build_q_param

_FIELDS = frozenset({"rut", "id_especialidad"})


def test_builds_the_documented_q_json_param():
    params = build_q_param({"rut": ("eq", "30123456")}, allowed_fields=_FIELDS)

    assert params == {"q": '{"rut":{"eq":"30123456"}}'}


def test_supports_several_fields_at_once():
    params = build_q_param(
        {"id_especialidad": ("eq", 7), "rut": ("eq", "30123456")}, allowed_fields=_FIELDS
    )

    assert json.loads(params["q"]) == {
        "id_especialidad": {"eq": 7},
        "rut": {"eq": "30123456"},
    }


def test_rejects_a_field_outside_the_allow_list():
    with pytest.raises(ValueError, match="habilitado"):
        build_q_param({"habilitado": ("eq", 1)}, allowed_fields=_FIELDS)


def test_rejects_an_operator_outside_the_allow_list():
    with pytest.raises(ValueError, match="drop"):
        build_q_param({"rut": ("drop", "x")}, allowed_fields=_FIELDS)


def test_untrusted_text_can_only_ever_become_a_json_value():
    # A patient-controlled value must never be able to smuggle in another
    # field or operator — it is serialized by json.dumps as a value, never
    # interpolated into the query string by hand.
    hostile = '30123456"},"habilitado":{"eq":"1'

    params = build_q_param({"rut": ("eq", hostile)}, allowed_fields=_FIELDS)

    assert json.loads(params["q"]) == {"rut": {"eq": hostile}}
