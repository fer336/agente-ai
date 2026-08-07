import hmac
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.application.messages.ingest_message import IngestMessageUseCase
from app.config.settings import Settings, get_settings
from app.infrastructure.chatwoot.webhook_payload import ChatwootMessageCreatedPayload

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAckResponse(BaseModel):
    """Acknowledgement returned to Chatwoot for every request past the secret check.

    `status="accepted"` means the event passed all filters and its DTO was
    handed off to `IngestMessageUseCase.execute()`. `status="ignored"` means
    the event was recognized but intentionally dropped (wrong inbox, private
    note, non-incoming message type, or a plausible-but-incomplete payload)
    — this is NOT an error, per spec: dropped events must still be
    acknowledged.
    """

    status: Literal["accepted", "ignored"]


@router.post(
    "/chatwoot/{secret}",
    summary="Receive a Chatwoot `message_created` outgoing webhook event",
    response_model=WebhookAckResponse,
)
async def receive_chatwoot_webhook(
    secret: str,
    payload: ChatwootMessageCreatedPayload,
    settings: Settings = Depends(get_settings),
    use_case: IngestMessageUseCase = Depends(get_ingest_message_use_case),
) -> WebhookAckResponse:
    """Chatwoot is the sole webhook counterparty (Meta -> Chatwoot -> us).

    The `{secret}` path segment is compared inline with
    `hmac.compare_digest` against `settings.chatwoot_webhook_secret` — no
    `Depends`-based auth wrapper, matching this design's flat-guard-clause
    convention (see `app/api/routes/health.py`). A mismatch returns 404,
    deliberately indistinguishable from an unregistered path. Meta/Chatwoot
    HMAC signature headers are explicitly out of scope for this change.

    `use_case.execute(dto)` is awaited here — its synchronous portion
    (dedupe, contact/conversation resolution, message persistence, the
    human-mode gate, and the debounce-window touch) runs in-request; only
    the deferred lock-acquire + Etapa-5-seam step (fired after the debounce
    window elapses) runs in a background `asyncio.create_task` that this
    request does NOT wait for. See `IngestMessageUseCase.execute`'s
    docstring/comments for the exact split.
    """
    if not hmac.compare_digest(secret, settings.chatwoot_webhook_secret):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid webhook secret")

    if not _passes_filters(payload, settings):
        return WebhookAckResponse(status="ignored")

    try:
        dto = payload.to_inbound_message_dto()
    except ValueError:
        # Plausible-but-incomplete payload (e.g. sender.phone_number
        # missing) — ack-and-drop rather than a 500, so Chatwoot does not
        # retry a request that will never succeed.
        return WebhookAckResponse(status="ignored")

    await use_case.execute(dto)
    return WebhookAckResponse(status="accepted")


def _passes_filters(payload: ChatwootMessageCreatedPayload, settings: Settings) -> bool:
    """Only `message_created` + `incoming` + non-private + configured inbox proceeds."""
    return (
        payload.event == "message_created"
        and payload.message_type == "incoming"
        and not payload.private
        and str(payload.inbox.id) == settings.chatwoot_inbox_id
    )
