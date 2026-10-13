import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.gateways import get_chatwoot_gateway, get_messaging_gateway
from app.api.dependencies.repositories import (
    get_chatwoot_mapping_repository,
    get_committing_conversation_repository,
)
from app.application.conversations.chatwoot_control import PauseBotFromChatwootUseCase
from app.application.conversations.reactivate_bot_from_chatwoot import (
    ReactivateBotFromChatwootUseCase,
)
from app.application.messages.forward_chatwoot_reply import ForwardChatwootReplyUseCase
from app.config.settings import Settings, get_settings
from app.domain.repositories.chatwoot_gateway import ChatwootGateway
from app.domain.repositories.chatwoot_mapping_repository import ChatwootMappingRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import MessagingGateway
from app.infrastructure.chatwoot.mapping_fallback import ChatwootContactMappingFallback
from app.infrastructure.chatwoot.schemas import (
    ChatwootConversationStatusChangedEventPayload,
    ChatwootConversationUpdatedEventPayload,
    ChatwootMessageCreatedEventPayload,
)
from app.infrastructure.chatwoot.webhook_parser import (
    extract_control_label_change,
    extract_resolved_conversation_id,
    extract_staff_reply,
    is_conversation_resolved_event,
    is_conversation_status_changed_event,
    is_conversation_updated_event,
    is_message_created_event,
)

logger = logging.getLogger(__name__)

#: Internal bot mode -> the Chatwoot control label it mirrors (for readable logs).
_CONTROL_LABEL_BY_MODE = {"human": "administracion", "agent": "agente"}

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class ChatwootWebhookAckResponse(BaseModel):
    """Same ack-and-drop contract as `app.api.routes.webhook`'s own
    response — see `WebhookAckResponse`'s docstring."""

    status: Literal["accepted", "ignored"]


@router.post(
    "/chatwoot/{secret}",
    summary=(
        "Receive a Chatwoot account-level webhook event: `message_created` "
        "(staff reply pauses the bot and is forwarded to WhatsApp), "
        "`conversation_updated` (manual control-label change), or "
        "`conversation_status_changed`/`conversation_resolved` (staff resolves the conversation, "
        "flips mode back to the bot)"
    ),
    response_model=ChatwootWebhookAckResponse,
)
async def receive_chatwoot_webhook(
    secret: str,
    payload: dict[str, object],
    settings: Settings = Depends(get_settings),
    messaging_gateway: MessagingGateway = Depends(get_messaging_gateway),
    chatwoot_gateway: ChatwootGateway = Depends(get_chatwoot_gateway),
    conversation_repository: ConversationRepository = Depends(
        get_committing_conversation_repository
    ),
    stored_mapping_repository: ChatwootMappingRepository = Depends(get_chatwoot_mapping_repository),
) -> ChatwootWebhookAckResponse:
    """Chatwoot is the "camino de vuelta" counterparty for the mirror this
    session built (WhatsApp -> Chatwoot is PR1; this route is the return
    path, Chatwoot -> WhatsApp).

    The `{secret}` path segment is compared inline with
    `hmac.compare_digest` against `settings.chatwoot_webhook_secret` — same
    flat-guard-clause convention as `app.api.routes.webhook`'s own YCloud
    counterpart. A mismatch returns 404, deliberately indistinguishable
    from an unregistered path. Chatwoot's own `X-Chatwoot-Signature` HMAC
    header (confirmed correct only for an ACCOUNT-level webhook — see this
    session's own plan report for why an inbox/Agent-Bot-level webhook was
    ruled out) is intentionally NOT verified here yet, matching this
    codebase's existing precedent of a path secret alone for YCloud too —
    left as a documented follow-up, not silently forgotten.

    Only `message_created`/`conversation_updated`/
    `conversation_status_changed` are handled; every other Chatwoot event
    type (`contact_created`, `conversation_created`, ...) is acknowledged
    but ignored.
    """
    if not hmac.compare_digest(secret, settings.chatwoot_webhook_secret):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invalid webhook secret")

    # Conversations without a stored mapping (created before the table was
    # cleared) are resolved through the Chatwoot contact instead of ignored.
    mapping_repository = ChatwootContactMappingFallback(stored_mapping_repository, chatwoot_gateway)

    event = str(payload.get("event", ""))
    logger.info("chatwoot_webhook.received event=%s", event)

    if is_message_created_event(event):
        message_payload = ChatwootMessageCreatedEventPayload.model_validate(payload)
        staff_reply = extract_staff_reply(message_payload)
        if staff_reply is None:
            return ChatwootWebhookAckResponse(status="ignored")

        chatwoot_conversation_id, content = staff_reply
        pause_bot = PauseBotFromChatwootUseCase(
            chatwoot_gateway, conversation_repository, mapping_repository
        )
        forward_reply = ForwardChatwootReplyUseCase(messaging_gateway, mapping_repository)
        try:
            # A genuine staff reply takes control even when the operator forgot to
            # apply `administracion` first: the label flips to `administracion`, so
            # the reply already goes out as administración.
            await pause_bot.execute(chatwoot_conversation_id, synchronize_label=True)
            forwarded = await forward_reply.execute(
                chatwoot_conversation_id, f"> Asesor\n{content}"
            )
        except Exception:
            # Best-effort, same ack-and-drop stance as every branch in
            # `app.api.routes.webhook` — a lookup/send failure here must
            # never turn into a 500 that Chatwoot retries.
            logger.warning(
                "chatwoot_webhook.forward_reply_failed chatwoot_conversation_id=%s",
                chatwoot_conversation_id,
                exc_info=True,
            )
        else:
            if forwarded:
                logger.info(
                    "chatwoot_webhook.reply_forwarded chatwoot_conversation_id=%s",
                    chatwoot_conversation_id,
                )
            else:
                # No mapping for this Chatwoot conversation (for example one created
                # before the mappings were cleared): nothing reached the patient.
                logger.warning(
                    "chatwoot_webhook.reply_not_forwarded_no_mapping chatwoot_conversation_id=%s",
                    chatwoot_conversation_id,
                )
        return ChatwootWebhookAckResponse(status="accepted")

    if is_conversation_updated_event(event):
        updated_payload = ChatwootConversationUpdatedEventPayload.model_validate(payload)
        control_change = extract_control_label_change(updated_payload)
        if control_change is None:
            # Keys only, never values: enough to spot a label change in a shape we do
            # not parse yet, without logging patient data.
            raw_changes = payload.get("changed_attributes")
            changed_keys = sorted(
                {
                    str(key)
                    for entry in (raw_changes if isinstance(raw_changes, list) else [])
                    if isinstance(entry, dict)
                    for key in entry
                }
            )
            logger.info(
                "chatwoot_webhook.conversation_updated_ignored changed_keys=%s", changed_keys
            )
            return ChatwootWebhookAckResponse(status="ignored")

        chatwoot_conversation_id, mode = control_change
        try:
            if mode == "human":
                pause_bot = PauseBotFromChatwootUseCase(
                    chatwoot_gateway, conversation_repository, mapping_repository
                )
                # Also drops a leftover `agente` label, so one click is enough.
                await pause_bot.execute(chatwoot_conversation_id, synchronize_label=True)
            else:
                reactivate_bot = ReactivateBotFromChatwootUseCase(
                    chatwoot_gateway, conversation_repository, mapping_repository
                )
                await reactivate_bot.execute(chatwoot_conversation_id)
        except Exception:
            logger.warning(
                "chatwoot_webhook.control_label_sync_failed chatwoot_conversation_id=%s label=%s",
                chatwoot_conversation_id,
                _CONTROL_LABEL_BY_MODE[mode],
                exc_info=True,
            )
        else:
            logger.info(
                "chatwoot_webhook.control_label_synced chatwoot_conversation_id=%s label=%s",
                chatwoot_conversation_id,
                _CONTROL_LABEL_BY_MODE[mode],
            )
        return ChatwootWebhookAckResponse(status="accepted")

    if is_conversation_status_changed_event(event) or is_conversation_resolved_event(event):
        status_payload = ChatwootConversationStatusChangedEventPayload.model_validate(payload)
        resolved_conversation_id = extract_resolved_conversation_id(status_payload)
        if resolved_conversation_id is None:
            return ChatwootWebhookAckResponse(status="ignored")

        reactivate_bot = ReactivateBotFromChatwootUseCase(
            chatwoot_gateway, conversation_repository, mapping_repository
        )
        try:
            await reactivate_bot.execute(resolved_conversation_id)
        except Exception:
            logger.warning(
                "chatwoot_webhook.reactivate_bot_failed chatwoot_conversation_id=%s",
                resolved_conversation_id,
                exc_info=True,
            )
        else:
            logger.info(
                "chatwoot_webhook.bot_reactivated chatwoot_conversation_id=%s",
                resolved_conversation_id,
            )
        return ChatwootWebhookAckResponse(status="accepted")

    return ChatwootWebhookAckResponse(status="ignored")
