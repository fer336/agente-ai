import httpx

from app.domain.value_objects.interactive_button import InteractiveButton
from app.infrastructure.ycloud.exceptions import YCloudAPIError


class YCloudClient:
    """`httpx`-based client for YCloud's WhatsApp Business API.

    UNVERIFIED against a live YCloud account (no live credentials/sandbox in
    this change) — the endpoint path (`POST /v2/whatsapp/messages`), the
    `X-API-Key` auth header, and the request/response JSON shapes below
    follow YCloud's publicly documented conventions, which mirror Meta's
    WhatsApp Cloud API message format. Confirm all of this against real
    YCloud API docs/credentials before production use — see this PR's
    report for the full list of open questions.
    """

    def __init__(self, base_url: str, api_key: str, whatsapp_number: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._whatsapp_number = whatsapp_number

    async def send_text(self, to: str, text: str) -> str:
        return await self._post_message(
            {
                "from": self._whatsapp_number,
                "to": to,
                "type": "text",
                "text": {"body": text},
            }
        )

    async def send_buttons(self, to: str, text: str, buttons: list[InteractiveButton]) -> str:
        return await self._post_message(
            {
                "from": self._whatsapp_number,
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": button.id, "title": button.title}}
                            for button in buttons
                        ]
                    },
                },
            }
        )

    async def _post_message(self, payload: dict[str, object]) -> str:
        url = f"{self._base_url}/v2/whatsapp/messages"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers={"X-API-Key": self._api_key}, json=payload
            )
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            data = response.json()
            return str(data["id"])
