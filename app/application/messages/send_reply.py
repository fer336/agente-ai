from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber


class SendReplyUseCase:
    """Sends an AI reply through the outbound messaging channel.

    Unlike the pre-YCloud design (Etapa 4's Chatwoot-era dual-write), there
    is no separate mirror call here: YCloud IS the WhatsApp channel, so a
    message sent through `MessagingGateway` is already visible to human
    agents in YCloud's own Shared Team Inbox — no second write to a
    distinct "mirror" gateway is needed.

    When `buttons` is given, sends an interactive button message
    (`MessagingGateway.send_buttons`) instead of plain text — needed by
    PRD.md §6's `INTERACTIVE_SELECTION`/`SENSITIVE_CONFIRMATION` states,
    which require a real tappable button, not a text reply the patient
    could type back verbatim (PRD.md §24.4: text/audio must never confirm
    a sensitive operation).
    """

    def __init__(self, messaging_gateway: MessagingGateway) -> None:
        self._messaging_gateway = messaging_gateway

    async def execute(
        self, to: PhoneNumber, text: str, buttons: list[InteractiveButton] | None = None
    ) -> None:
        if buttons:
            await self._messaging_gateway.send_buttons(to, text, buttons)
        else:
            await self._messaging_gateway.send_text_message(to, text)

    async def send_typing_indicator(self, wamid: str) -> None:
        await self._messaging_gateway.send_typing_indicator(wamid)
