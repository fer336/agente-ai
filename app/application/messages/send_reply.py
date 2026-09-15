from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from app.domain.entities.sent_message import SentMessage
from app.domain.repositories.gateways import MessagingGateway
from app.domain.repositories.sent_message_repository import SentMessageRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.phone_number import PhoneNumber

SentMessageRepositoriesProvider = Callable[
    [], AbstractAsyncContextManager["SentMessageRepository"]
]


class SendReplyUseCase:
    """Sends an AI reply through the outbound messaging channel.

    Unlike the pre-YCloud design (Etapa 4's Chatwoot-era dual-write), there
    is no separate mirror call here: YCloud IS the WhatsApp channel, so a
    message sent through `MessagingGateway` is already visible to human
    agents in YCloud's own Shared Team Inbox — no second write to a
    distinct "mirror" gateway is needed.

    `flow`/`location`/`list_message`/`buttons` are mutually exclusive — a
    node should only ever set one — checked in that order of specificity.
    `location` sends WhatsApp's native location card
    (`MessagingGateway.send_location`), which has no room for a `text`
    body of its own (WhatsApp's location message type carries only
    coordinates/name/address), so `text` is ignored on that path.
    `list_message` sends an interactive list (up to 10 rows — beyond
    that, a node falls back to a numbered text list instead, e.g. the
    specialty catalog). Otherwise, when `buttons` is given, sends an
    interactive button message (`MessagingGateway.send_buttons`) instead
    of plain text — needed by PRD.md §6's `INTERACTIVE_SELECTION`/
    `SENSITIVE_CONFIRMATION` states, which require a real tappable button,
    not a text reply the patient could type back verbatim (PRD.md §24.4:
    text/audio must never confirm a sensitive operation).

    Every send is correlated to `conversation_id` via `SentMessageRepository`
    (keyed by the external `MessagingGateway` message id every `send_*`
    method already returns) — this is what lets a later async
    `whatsapp.message.updated` delivery-failure webhook be attributed to a
    conversation/patient instead of vanishing silently (see
    `app.domain.entities.sent_message.SentMessage`'s own docstring).
    `sent_message_repositories_provider` follows the same "singleton use
    case, fresh session per call" pattern as
    `IngestMessageUseCase.repositories_provider` — `SendReplyUseCase`
    itself is a process-level singleton (built once by
    `app.api.dependencies.gateways.get_agent_invoker`/
    `app.api.dependencies.use_cases.get_ingest_message_use_case`), so it
    cannot hold one long-lived SQLAlchemy session.
    """

    def __init__(
        self,
        messaging_gateway: MessagingGateway,
        sent_message_repositories_provider: SentMessageRepositoriesProvider,
    ) -> None:
        self._messaging_gateway = messaging_gateway
        self._sent_message_repositories_provider = sent_message_repositories_provider

    async def execute(
        self,
        conversation_id: ConversationId,
        to: PhoneNumber,
        text: str,
        buttons: list[InteractiveButton] | None = None,
        image_url: str | None = None,
        flow: FlowRequest | None = None,
        location: LocationRequest | None = None,
        list_message: ListMessage | None = None,
    ) -> str:
        if flow is not None:
            external_id = await self._messaging_gateway.send_flow(to, text, flow)
        elif location is not None:
            external_id = await self._messaging_gateway.send_location(to, location)
        elif list_message is not None:
            external_id = await self._messaging_gateway.send_list(to, text, list_message)
        elif buttons:
            external_id = await self._messaging_gateway.send_buttons(to, text, buttons, image_url)
        else:
            external_id = await self._messaging_gateway.send_text_message(to, text)

        async with self._sent_message_repositories_provider() as sent_messages:
            await sent_messages.save(
                SentMessage(
                    id=external_id,
                    conversation_id=str(conversation_id),
                    sent_at=datetime.now(UTC),
                )
            )

        return external_id

    async def send_typing_indicator(self, wamid: str) -> None:
        await self._messaging_gateway.send_typing_indicator(wamid)
