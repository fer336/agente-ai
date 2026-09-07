import json

#: Marks `InboundMessageDTO.button_payload`/`AgentState.button_payload` as a
#: completed WhatsApp Flow submission rather than a tapped button id.
#: Produced by `app.infrastructure.ycloud.webhook_parser` (parsing the
#: inbound webhook) and consumed by `app.agent.nodes.appointment` (the
#: stage waiting on a Flow response) — lives here, in `domain`, because
#: neither side may import from the other (hexagonal dependency rule):
#: `resolve_interaction.py` already routes ANY non-`None` `button_payload`
#: straight back to `appointment` mid-stage without a wasted LLM call
#: (PRD.md §6: "Botón -> Intención conocida"), and a Flow submission is
#: exactly that same kind of deterministic, machine-readable signal.
FLOW_RESPONSE_PAYLOAD_PREFIX = "FLOW_RESPONSE:"


def parse_flow_response_payload(button_payload: str | None) -> dict[str, object] | None:
    """Extracts a completed Flow's fields from `button_payload`, or `None`
    when it isn't a Flow response at all (no prefix) or its JSON is
    malformed — callers must treat both the same way: there is nothing
    usable to act on.
    """
    if button_payload is None or not button_payload.startswith(FLOW_RESPONSE_PAYLOAD_PREFIX):
        return None
    raw = button_payload.removeprefix(FLOW_RESPONSE_PAYLOAD_PREFIX)
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
