from app.domain.entities.runtime_agent_config import RuntimeAgentConfig

FILTER_OFF = "off"
FILTER_DENY = "deny"
FILTER_ALLOW = "allow"
CONTACT_FILTER_MODES = (FILTER_OFF, FILTER_DENY, FILTER_ALLOW)


def normalize_phone(raw: str) -> str:
    """Digits only, so `+54 9 11-1234` and `54911 1234` compare equal."""
    return "".join(ch for ch in raw if ch.isdigit())


def agent_may_respond(config: RuntimeAgentConfig, phone: str) -> bool:
    """Whether the agent may send anything on its own to `phone`.

    The global pause overrides every filter. `deny` blocks the listed numbers,
    `allow` blocks everybody except the listed numbers.
    """
    if config.agent_paused:
        return False
    normalized = normalize_phone(phone)
    listed = normalized in {normalize_phone(p) for p in config.contact_filter_phones}
    if config.contact_filter_mode == FILTER_DENY:
        return not listed
    if config.contact_filter_mode == FILTER_ALLOW:
        return listed
    return True
