from app.domain.repositories.gateways import ChatwootConversationGateway, MessagingGateway
from app.domain.value_objects.phone_number import PhoneNumber


class SendReplyUseCase:
    """Outbound dual-write (design doc's Data Flow "Outbound dual-write" step).

    Sends an AI reply through BOTH channels with the identical text:
    - `MessagingGateway.send_text_message` — direct Meta Cloud API send
      (existing since Etapa 3, unchanged).
    - `ChatwootConversationGateway.mirror_message` — mirrors the same text
      into the Chatwoot conversation thread under an Agent Bot sender
      identity (this phase), so human agents watching Chatwoot see the
      AI's reply without it ever re-entering `IngestMessageUseCase` (the
      webhook route's `message_type == "incoming"` filter, established in
      Phase 2, already drops every outgoing/mirrored event structurally —
      see the Phase 5 mode-flip regression test).

    No production caller wires this yet: Etapa 5's future LangGraph
    reply-producing node is the intended caller once it exists. Building
    and testing this use case now keeps the dual-write behavior covered
    ahead of that integration — same swap-point-ready pattern as
    `AgentInvoker`/`NotImplementedAgentInvoker`.
    """

    def __init__(
        self,
        messaging_gateway: MessagingGateway,
        chatwoot_gateway: ChatwootConversationGateway,
    ) -> None:
        self._messaging_gateway = messaging_gateway
        self._chatwoot_gateway = chatwoot_gateway

    async def execute(self, to: PhoneNumber, chatwoot_conversation_id: str, text: str) -> None:
        await self._messaging_gateway.send_text_message(to, text)
        await self._chatwoot_gateway.mirror_message(chatwoot_conversation_id, text)
