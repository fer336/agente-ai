import httpx

from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.ycloud.exceptions import YCloudAPIError


class YCloudHandoffGateway:
    """`httpx`-based real implementation of the `HumanHandoffGateway` port.

    HIGHEST-UNCERTAINTY adapter in this change. Per PRD §21, once
    `conversation_mode` flips to `HUMAN` the bot simply stops responding —
    administración continues from the same YCloud Shared Team Inbox thread,
    which YCloud already shows without any extra API call (it IS the
    WhatsApp channel). There is no PRD-mandated or publicly confirmed
    YCloud "assign/escalate conversation" endpoint this adapter must call.

    This implementation tags the conversation via a best-guess
    `PUT /v2/whatsapp/conversations/{phone}/labels` call so a human agent
    can filter escalated threads in the Shared Inbox — modeled on YCloud's
    publicly documented conversation-labeling convention, UNVERIFIED
    against a live account. Confirm the endpoint (or confirm no call is
    needed at all, since the mode flip alone may be sufficient) against
    real YCloud API docs before production use — see this PR's report.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def request_handoff(self, conversation_id: ConversationId, reason: str) -> None:
        phone = str(conversation_id).removeprefix("ycloud-")
        url = f"{self._base_url}/v2/whatsapp/conversations/{phone}/labels"
        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"X-API-Key": self._api_key},
                json={"labels": ["handoff"], "note": reason},
            )
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}"
                )
