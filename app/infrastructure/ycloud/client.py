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

    async def send_buttons(
        self,
        to: str,
        text: str,
        buttons: list[InteractiveButton],
        image_url: str | None = None,
    ) -> str:
        interactive: dict[str, object] = {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": button.id, "title": button.title}}
                    for button in buttons
                ]
            },
        }
        if image_url is not None:
            interactive["header"] = {"type": "image", "image": {"link": image_url}}
        return await self._post_message(
            {
                "from": self._whatsapp_number,
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            }
        )

    async def send_typing_indicator(self, wamid: str) -> None:
        """`POST /v2/whatsapp/inboundMessages/{wamid}/typingIndicator` —
        marks the given inbound message as read and shows "typing..." to
        the patient. Per YCloud's own docs: dismissed automatically after
        25s or as soon as we actually send a reply, whichever is first —
        callers should only fire this right before doing real work that
        will end in a reply, never speculatively.
        """
        url = f"{self._base_url}/v2/whatsapp/inboundMessages/{wamid}/typingIndicator"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers={"X-API-Key": self._api_key})
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

    async def get_media(self, media_id: str) -> dict[str, object]:
        """`GET /v1/media/{media_id}` — resolves a webhook's opaque media
        `id` to a short-lived download URL + declared MIME type (+ sha256
        when reported), per Meta's WhatsApp Cloud API media-metadata
        convention YCloud mirrors (PRD.md §24.1: "Descargar el archivo desde
        YCloud"). UNVERIFIED against a live YCloud account — see this
        module's own docstring.
        """
        url = f"{self._base_url}/v1/media/{media_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"X-API-Key": self._api_key})
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            data = response.json()
            return dict(data)

    async def get_contact(self, contact_id: str) -> dict[str, object]:
        """`GET /v2/contact/contacts/{contact_id}` — resolves a YCloud
        contact id to its `phoneNumber` (and other contact fields). Needed
        because YCloud's `contact.attributes_changed` webhook event only
        ever carries the contact's opaque id, never its phone number.
        UNVERIFIED against a live YCloud account — see this module's own
        docstring.
        """
        url = f"{self._base_url}/v2/contact/contacts/{contact_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"X-API-Key": self._api_key})
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            data = response.json()
            return dict(data)

    async def find_contact_by_phone(self, phone: str) -> dict[str, object] | None:
        """`GET /v2/contact/contacts?filter.phoneNumber={phone}&limit=1` —
        resolves a phone number to its YCloud contact (id + current tags),
        the reverse of `get_contact`. Needed to tag a contact from our side
        (e.g. marking a handoff) when we only have the patient's phone.
        Returns `None` when no contact matches. UNVERIFIED against a live
        YCloud account — see this module's own docstring.
        """
        url = f"{self._base_url}/v2/contact/contacts"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"X-API-Key": self._api_key},
                params={"filter.phoneNumber": phone, "limit": 1},
            )
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            items = response.json().get("items") or []
            return dict(items[0]) if items else None

    async def update_contact_tags(self, contact_id: str, tags: list[str]) -> None:
        """`PATCH /v2/contact/contacts/{contact_id}` — replaces the
        contact's ENTIRE tag list with `tags` (YCloud's tags API is not
        additive: callers must read the current list first, e.g. via
        `find_contact_by_phone`/`get_contact`, and pass the merged result).
        UNVERIFIED against a live YCloud account — see this module's own
        docstring.
        """
        url = f"{self._base_url}/v2/contact/contacts/{contact_id}"
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url, headers={"X-API-Key": self._api_key}, json={"tags": tags}
            )
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

    async def _post_message(self, payload: dict[str, object]) -> str:
        url = f"{self._base_url}/v2/whatsapp/messages"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers={"X-API-Key": self._api_key}, json=payload)
            if response.is_error:
                raise YCloudAPIError(
                    f"YCloud API returned {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )
            data = response.json()
            return str(data["id"])
