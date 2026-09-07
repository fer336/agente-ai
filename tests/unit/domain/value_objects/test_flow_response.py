from app.domain.value_objects.flow_response import (
    FLOW_RESPONSE_PAYLOAD_PREFIX,
    parse_flow_response_payload,
)


def test_parses_a_valid_flow_response_payload():
    payload = f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456"}}'

    assert parse_flow_response_payload(payload) == {
        "full_name": "Rosa Gomez",
        "dni": "30123456",
    }


def test_returns_none_for_none_payload():
    assert parse_flow_response_payload(None) is None


def test_returns_none_for_a_plain_button_payload_without_the_prefix():
    assert parse_flow_response_payload("CONFIRM_APPOINTMENT") is None


def test_returns_none_for_malformed_json_after_the_prefix():
    assert parse_flow_response_payload(f"{FLOW_RESPONSE_PAYLOAD_PREFIX}not-json") is None


def test_returns_none_when_the_json_is_not_an_object():
    assert parse_flow_response_payload(f"{FLOW_RESPONSE_PAYLOAD_PREFIX}[1, 2, 3]") is None
