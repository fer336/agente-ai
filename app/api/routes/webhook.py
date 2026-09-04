import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.gateways import get_messaging_gateway
from app.api.dependencies.repositories import get_conversation_repository
from app.api.dependencies.use_cases import get_ingest_message_use_case
from app.application.conversations.sync_conversation_mode_from_tag import (
    SyncConversationModeFromTagUseCase,
)
from app.application.messages.ingest_message import IngestMessageUseCase
from app.config.settings import Settings, get_settings
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import MessagingGateway
from app.infrastructure.ycloud.schemas import (
    YCloudContactAttributesChangedEventPayload,
    YCloudInboundEventPayload,
)
from app.infrastructure.ycloud.webhook_parser import (
    extract_tag_mode_change,
    is_processable_message,
    is_tag_mode_change_event,
    to_inbound_message_dto,
)

logger = logging.getLogger(__name__)

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
    summary=(
        "Receive a YCloud webhook event: `whatsapp.inbound_message.received` "
        "or `contact.attributes_changed` (tag-driven bot/human toggle)"
    ),
    response_model=WebhookAckResponse,
)
async def receive_ycloud_webhook(
    secret: str,
    payload: dict[str, object],
    settings: Settings = Depends(get_settings),
    use_case: IngestMessageUseCase = Depends(get_ingest_message_use_case),
    messaging_gateway: MessagingGateway = Depends(get_messaging_gateway),
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
) -> WebhookAckResponse:
    """YCloud is the sole webhook counterparty (WhatsApp -> YCloud -> us).

    The `{secret}` path segment is compared inline with
    `hmac.compare_digest` against `settings.ycloud_webhook_secret` — no
    `Depends`-based auth wrapper, matching this design's flat-guard-clause
    convention (see `app/api/routes/health.py`). A mismatch returns 404,
    deliberately indistinguishable from an unregistered path. YCloud's own
    HMAC signature headers (PRD §74.1) are explicitly out of scope for this
    change — see this PR's report.

    The body is accepted as a raw `dict` (not one fixed pydantic model)
    because this single endpoint now fans out on `payload["type"]` to two
    unrelated YCloud event shapes: an inbound WhatsApp message, or a
    `contact.attributes_changed` tag change (the "Humano" tag's
    presence/absence drives the bot/human toggle — see
    `SyncConversationModeFromTagUseCase`).
    Each branch validates into its own specific schema before use.

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

    event_type = str(payload.get("type", ""))
    # Temporary diagnostic: uvicorn's own access log line never shows the
    # event TYPE, only the HTTP status — every webhook call looks identical
    # from that alone. Remove once the tag-driven toggle is confirmed
    # working end-to-end against a live YCloud account.
    logger.info("webhook.received event_type=%s", event_type)

    if is_tag_mode_change_event(event_type):
        tag_payload = YCloudContactAttributesChangedEventPayload.model_validate(payload)
        change = extract_tag_mode_change(tag_payload)
        if change is None:
            logger.info("webhook.tag_change_not_matched raw_payload=%s", payload)
            return WebhookAckResponse(status="ignored")

        ycloud_contact_id, mode = change
        sync_mode = SyncConversationModeFromTagUseCase(messaging_gateway, conversation_repository)
        try:
            await sync_mode.execute(ycloud_contact_id, mode)
        except Exception:
            # Best-effort: a YCloud contact-lookup failure must never turn
            # into a 500 that YCloud retries — same ack-and-drop stance as
            # the message-parsing branch below.
            logger.warning(
                "webhook.tag_mode_sync_failed ycloud_contact_id=%s mode=%s",
                ycloud_contact_id,
                mode,
                exc_info=True,
            )
        else:
            logger.info(
                "webhook.tag_mode_synced ycloud_contact_id=%s mode=%s", ycloud_contact_id, mode
            )
        return WebhookAckResponse(status="accepted")

    message_payload = YCloudInboundEventPayload.model_validate(payload)
    if not is_processable_message(message_payload, settings.ycloud_whatsapp_number):
        return WebhookAckResponse(status="ignored")

    try:
        dto = to_inbound_message_dto(message_payload)
    except ValueError:
        # Plausible-but-incomplete payload (e.g. sender phone missing) —
        # ack-and-drop rather than a 500, so YCloud does not retry a
        # request that will never succeed.
        return WebhookAckResponse(status="ignored")

    await use_case.execute(dto)
    return WebhookAckResponse(status="accepted")
