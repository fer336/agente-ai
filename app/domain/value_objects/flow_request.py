from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FlowRequest:
    """Everything needed to send a WhatsApp Flow message (opens a single
    screen directly — every Flow in this codebase is single-screen, see
    `app.infrastructure.ycloud.flows`).

    `flow_token` is caller-generated and round-trips back in the
    completion webhook's `nfm_reply` — this codebase uses the
    `ConversationId` itself, since that's already enough to correlate the
    submission to a conversation.
    """

    flow_id: str
    flow_screen_id: str
    flow_cta: str
    flow_token: str
