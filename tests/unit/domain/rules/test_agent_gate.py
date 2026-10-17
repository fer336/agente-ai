from datetime import UTC, datetime

import pytest

from app.domain.entities.runtime_agent_config import RuntimeAgentConfig
from app.domain.rules.agent_gate import agent_may_respond, normalize_phone


def _config(**overrides: object) -> RuntimeAgentConfig:
    defaults: dict[str, object] = {
        "id": "default",
        "model": "m",
        "temperature": 0.0,
        "debounce_seconds": 1,
        "classify_intent_prompt": "c",
        "extract_information_prompt": "e",
        "generate_response_prompt": "g",
        "updated_at": datetime(2026, 10, 1, tzinfo=UTC),
        "updated_by": "admin",
    }
    defaults.update(overrides)
    return RuntimeAgentConfig(**defaults)  # type: ignore[arg-type]


def test_normalize_phone_keeps_digits_only():
    assert normalize_phone("+54 9 11-1234 5678") == "5491112345678"


def test_defaults_let_every_contact_through():
    assert agent_may_respond(_config(), "5491112345678") is True


def test_paused_blocks_everybody():
    assert agent_may_respond(_config(agent_paused=True), "5491112345678") is False


@pytest.mark.parametrize(
    ("mode", "phones"),
    [("allow", ("5491112345678",)), ("deny", ("5490000000000",)), ("off", ())],
)
def test_pause_overrides_any_filter(mode: str, phones: tuple[str, ...]):
    config = _config(agent_paused=True, contact_filter_mode=mode, contact_filter_phones=phones)

    assert agent_may_respond(config, "5491112345678") is False


def test_deny_blocks_only_listed_numbers():
    config = _config(contact_filter_mode="deny", contact_filter_phones=("5491112345678",))

    assert agent_may_respond(config, "+54 9 11 1234-5678") is False
    assert agent_may_respond(config, "5491199999999") is True


def test_allow_answers_only_listed_numbers():
    config = _config(contact_filter_mode="allow", contact_filter_phones=("5491112345678",))

    assert agent_may_respond(config, "5491112345678") is True
    assert agent_may_respond(config, "5491199999999") is False


def test_off_mode_ignores_a_stored_list():
    config = _config(contact_filter_mode="off", contact_filter_phones=("5491112345678",))

    assert agent_may_respond(config, "5491112345678") is True
