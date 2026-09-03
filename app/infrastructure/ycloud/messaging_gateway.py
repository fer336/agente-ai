from app.application.errors.error_types import YCLOUD_AUTH_ERROR, YCLOUD_SEND_FAILURE
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.observability.tool_tracing import traced_call
from app.infrastructure.ycloud.client import YCloudClient
from app.infrastructure.ycloud.exceptions import YCloudAPIError

_PROVIDER = "ycloud"


def _http_status_of(exc: Exception) -> str | None:
    if isinstance(exc, YCloudAPIError) and exc.status_code is not None:
        return str(exc.status_code)
    return None


def _error_type_of(exc: Exception) -> str:
    """Maps a YCloud send failure to PRD.md §43/§46's `ycloud_auth_error`
    vs `ycloud_send_failure` (a 401/403 needs a human NOW; any other send
    failure is more likely transient — see `error_types.py`'s own module
    docstring for why these are more specific than §43.2's literal list).
    """
    if isinstance(exc, YCloudAPIError) and exc.status_code in (401, 403):
        return YCLOUD_AUTH_ERROR
    return YCLOUD_SEND_FAILURE


class YCloudMessagingGateway:
    """`YCloudClient`-based real implementation of the `MessagingGateway` port.

    Not wired into DI yet (see `app.api.dependencies.gateways`, which still
    binds `FakeYCloudMessagingGateway` by default, matching every other
    gateway's fake-by-default swap-point convention in this codebase).
    """

    def __init__(self, client: YCloudClient) -> None:
        self._client = client

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        return await traced_call(
            tool_name="SendTextMessageTool",
            provider=_PROVIDER,
            operation="send_text_message",
            # `to`/`text` are never included — a WhatsApp number and the
            # actual message content are exactly what PRD.md §41 (and §47's
            # "Telegram no deberá recibir teléfonos completos") means by
            # "información sensible innecesaria".
            request_summary=f"text_length={len(text)}",
            call=lambda: self._client.send_text(str(to), text),
            response_summary=lambda external_id: f"external_message_id={external_id}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def send_buttons(
        self, to: PhoneNumber, text: str, buttons: list[InteractiveButton]
    ) -> str:
        return await traced_call(
            tool_name="SendButtonsTool",
            provider=_PROVIDER,
            operation="send_buttons",
            request_summary=f"text_length={len(text)} buttons={len(buttons)}",
            call=lambda: self._client.send_buttons(str(to), text, buttons),
            response_summary=lambda external_id: f"external_message_id={external_id}",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def get_contact_phone(self, ycloud_contact_id: str) -> PhoneNumber | None:
        return await traced_call(
            tool_name="GetContactPhoneTool",
            provider=_PROVIDER,
            operation="get_contact_phone",
            request_summary=f"ycloud_contact_id={ycloud_contact_id}",
            call=lambda: self._resolve_contact_phone(ycloud_contact_id),
            response_summary=lambda phone: "found" if phone is not None else "not_found",
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )

    async def _resolve_contact_phone(self, ycloud_contact_id: str) -> PhoneNumber | None:
        data = await self._client.get_contact(ycloud_contact_id)
        raw_phone = data.get("phoneNumber")
        if not raw_phone or not str(raw_phone).strip():
            return None
        try:
            return PhoneNumber(str(raw_phone))
        except ValueError:
            return None

    async def send_typing_indicator(self, wamid: str) -> None:
        await traced_call(
            tool_name="SendTypingIndicatorTool",
            provider=_PROVIDER,
            operation="send_typing_indicator",
            request_summary="typing_indicator",
            call=lambda: self._client.send_typing_indicator(wamid),
            http_status_of=_http_status_of,
            error_type_of=_error_type_of,
        )
