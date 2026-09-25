import httpx

from app.infrastructure.chatwoot.exceptions import ChatwootAPIError


class ChatwootClient:
    """`httpx`-based client for Chatwoot's Application API.

    Verified live against a real self-hosted instance during this
    session's setup (not a documentation-only guess, unlike
    `app.infrastructure.ycloud.client.YCloudClient`'s own "UNVERIFIED"
    caveat): `POST /contacts`, `POST /contacts/filter`,
    `POST /conversations`, `POST /conversations/{id}/messages`, and
    `POST /conversations/{id}/labels` all confirmed against a running
    account, including the exact `sender.type` values Chatwoot returns
    (`"contact"`/`"agent_bot"`/`"user"`) and the 422 shape on a duplicate
    `identifier`. `GET /conversations/{id}/labels` is confirmed instead
    against Chatwoot's published OpenAPI spec (`conversation_labels`
    schema — `{"payload": [<label>, ...]}`), not against the live
    instance.

    Two credentials are used for different calls — confirmed empirically,
    not assumed: `api_access_token` (a real agent/admin's personal token)
    is required for contact create/search and label management, which a
    Chatwoot Agent Bot token cannot access; `agent_bot_token` is used only
    when posting an outgoing (bot-authored) message, so it comes back
    attributed to `sender.type == "agent_bot"` instead of `"user"`.
    """

    def __init__(
        self,
        base_url: str,
        account_id: str,
        api_access_token: str,
        agent_bot_token: str,
        inbox_id: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._account_id = account_id
        self._api_access_token = api_access_token
        self._agent_bot_token = agent_bot_token
        self._inbox_id = inbox_id

    async def find_contact_by_identifier(self, identifier: str) -> dict[str, object] | None:
        """`POST /contacts/filter` — exact match, confirmed reliable.
        `/contacts/search` is deliberately NOT used here: Chatwoot's own
        docs contradict themselves on whether it matches phone numbers."""
        body: dict[str, object] = {
            "payload": [
                {
                    "attribute_key": "identifier",
                    "filter_operator": "equal_to",
                    "values": [identifier],
                    "query_operator": None,
                }
            ]
        }
        data = await self._request("POST", "/contacts/filter", self._api_access_token, body)
        payload = data.get("payload") or []
        if not isinstance(payload, list) or not payload:
            return None
        return dict(payload[0])

    async def create_contact(self, identifier: str, phone: str, name: str) -> dict[str, object]:
        """`POST /contacts` — `identifier` is set to the canonical phone
        number, our own dedup key. Raises `ChatwootAPIError(status_code=422)`
        if a contact with this `identifier`/`phone_number` already exists —
        callers should fall back to `find_contact_by_identifier` on that,
        not retry blindly."""
        data = await self._request(
            "POST",
            "/contacts",
            self._api_access_token,
            {
                "inbox_id": int(self._inbox_id),
                "name": name,
                "identifier": identifier,
                "phone_number": phone,
            },
        )
        payload = data.get("payload")
        return dict(payload["contact"]) if isinstance(payload, dict) else data

    async def create_conversation(self, source_id: str, contact_id: str) -> str:
        """`POST /conversations` — no idempotent "find or create" exists in
        Chatwoot's API; the caller must track the returned id itself."""
        data = await self._request(
            "POST",
            "/conversations",
            self._api_access_token,
            {
                "source_id": source_id,
                "inbox_id": int(self._inbox_id),
                "contact_id": int(contact_id),
            },
        )
        return str(data["id"])

    async def create_message(self, conversation_id: str, content: str, message_type: str) -> None:
        """`message_type` is `"incoming"` (patient) or `"outgoing"` (bot).
        Outgoing messages authenticate with the Agent Bot token so they
        come back attributed to `sender.type == "agent_bot"` — confirmed
        empirically, NOT the `"AgentBot"` casing one Chatwoot doc page
        suggests."""
        token = self._agent_bot_token if message_type == "outgoing" else self._api_access_token
        await self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            token,
            {"content": content, "message_type": message_type},
        )

    async def get_conversation_labels(self, conversation_id: str) -> list[str]:
        """`GET /conversations/{id}/labels` — confirmed against Chatwoot's
        published OpenAPI spec (`conversation_labels` schema, application
        API group, `chatwoot/chatwoot` `develop` branch): returns
        `{"payload": [<label>, ...]}`, the conversation's current label
        set. Same `api_access_token` auth as `set_conversation_labels`."""
        data = await self._request(
            "GET", f"/conversations/{conversation_id}/labels", self._api_access_token
        )
        payload = data.get("payload") or []
        return [str(label) for label in payload] if isinstance(payload, list) else []

    async def set_conversation_labels(self, conversation_id: str, labels: list[str]) -> None:
        """Overwrites the conversation's ENTIRE label set — confirmed:
        Chatwoot's labels API is not additive. Callers must pass the full
        desired set (see `ChatwootConversationGateway`'s read-modify-write
        around `get_conversation_labels`), not just the label being added."""
        await self._request(
            "POST",
            f"/conversations/{conversation_id}/labels",
            self._api_access_token,
            {"labels": labels},
        )

    async def _request(
        self, method: str, path: str, token: str, json: dict[str, object] | None = None
    ) -> dict[str, object]:
        url = f"{self._base_url}/api/v1/accounts/{self._account_id}{path}"
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, url, headers={"api_access_token": token}, json=json
            )
            if response.is_error:
                raise ChatwootAPIError(
                    f"Chatwoot API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            if not response.content:
                return {}
            return dict(response.json())
