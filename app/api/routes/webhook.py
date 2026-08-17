import hmac
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.application.messages.ingest_message import IngestMessageUseCase
from app.config.settings import Settings, get_settings
from app.infrastructure.ycloud.schemas import YCloudInboundEventPayload
from app.infrastructure.ycloud.webhook_parser import (
    is_processable_message,
    to_inbound_message_dto,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAckResponse(BaseModel):
    """Acknowledgement returned to YCloud for every request past the secret check.

    `status="accepted"` means the event passed all filters and its DTO was
    handed off to `IngestMessageUseCase.execute()`. `status="ignored"` means
    the event was recognized but intentionally dropped (wrong WhatsApp
    number, non-text message type, or a plausible-but-incomplete payload)
    — this is NOT an error, per spec: dropped events must still be
    acknowledged.
    """

    status: Literal["accepted", "ignored"]


@router.post(
    "/ycloud/{secret}",
    summary="Receive a YCloud `whatsapp.inbound_message.received` webhook event",
    response_model=WebhookAckResponse,
)
async def receive_ycloud_webhook(
    secret: str,
    payload: YCloudInboundEventPayload,
    settings: Settings = Depends(get_settings),
    use_case: IngestMessageUseCase = Depends(get_ingest_message_use_case),
) -> WebhookAckResponse:
    """YCloud is the sole webhook counterparty (WhatsApp -> YCloud -> us).

    The `{secret}` path segment is compared inline with
    `hmac.compare_digest` against `settings.ycloud_webhook_secret` — no
    `Depends`-based auth wrapper, matching this design's flat-guard-clause
    convention (see `app/api/routes/health.py`). A mismatch returns 404,
    deliberately indistinguishable from an unregistered path. YCloud's own
    HMAC signature headers (PRD §74.1) are explicitly out of scope for this
    change — see this PR's report.

    `use_case.execute(dto)` is awaited here — its synchronous portion
    (dedupe, contact/conversation resolution, message persistence, the
    human-mode gate, and the debounce-window touch) runs in-request; only
    the deferred lock-acquire + Etapa-5-seam step (fired after the debounce
    window elapses) runs in a background `asyncio.create_task` that this
    request does NOT wait for. See `IngestMessageUseCase.execute`'s
    docstring/comments for the exact split.
    """
    if not hmac.compare_digest(secret, settings.ycloud_webhook_secret):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid webhook secret")

    if not is_processable_message(payload, settings.ycloud_whatsapp_number):
        return WebhookAckResponse(status="ignored")

    try:
        dto = to_inbound_message_dto(payload)
    except ValueError:
        # Plausible-but-incomplete payload (e.g. sender phone missing) —
        # ack-and-drop rather than a 500, so YCloud does not retry a
        # request that will never succeed.
        return WebhookAckResponse(status="ignored")

    await use_case.execute(dto)
    return WebhookAckResponse(status="accepted")
