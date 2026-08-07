import httpx


class ChatwootConversationGateway:
    """`httpx`-based real implementation of the `ChatwootConversationGateway` port.

    Mirrors an AI-sent reply into a Chatwoot conversation thread via
    Chatwoot's "Create a new message" REST API
    (`POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages`).

    Sender identity (the "Agent Bot" tag from the design's Data Flow) comes
    from WHICH access token authenticates the call, not a request
    parameter — Chatwoot attributes `sender.type` server-side based on the
    calling token's own type. `api_token` here MUST be provisioned as a
    Chatwoot **Agent Bot** access token, not a regular human agent's token;
    using a human agent's token would defeat the entire point of tagging
    mirrored writes so they're distinguishable from a real human reply.
    This constraint is unverified against a live Chatwoot instance in this
    etapa (no live Chatwoot credentials in dev) — see the Etapa 4 design
    doc's Open Questions.

    Not wired into DI yet (see `app.api.dependencies.gateways`, which still
    binds `FakeChatwootConversationGateway` by default, matching every
    other gateway's fake-by-default swap-point convention in this
    codebase). This class exists as the ready-to-use real adapter for
    whenever live Chatwoot credentials/wiring land.
    """

    def __init__(self, base_url: str, account_id: str, api_token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._account_id = account_id
        self._api_token = api_token

    async def mirror_message(self, chatwoot_conversation_id: str, text: str) -> None:
        url = (
            f"{self._base_url}/api/v1/accounts/{self._account_id}"
            f"/conversations/{chatwoot_conversation_id}/messages"
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"api_access_token": self._api_token},
                json={"content": text, "message_type": "outgoing"},
            )
            response.raise_for_status()
