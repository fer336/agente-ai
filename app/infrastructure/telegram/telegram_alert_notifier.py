import httpx

from app.application.errors.error_types import TELEGRAM_ERROR
from app.infrastructure.observability.tool_tracing import traced_call

_PROVIDER = "telegram"


class TelegramAlertNotifier:
    """`httpx`-based `AlertNotifier` adapter for the Telegram Bot API's
    `sendMessage` endpoint (PRD.md §47).

    UNVERIFIED against a live Telegram bot (no live bot token in this
    environment — see this change's report, same honesty convention as
    `GroqTranscriptionGateway`). Endpoint shape follows Telegram's publicly
    documented Bot API (`POST {base_url}/bot{token}/sendMessage`, JSON body
    `{"chat_id": ..., "text": ...}`). Confirm against real Telegram
    docs/credentials before production use.

    A failed delivery raises `RuntimeError` — the caller
    (`ErrorService.notify_telegram`) is responsible for catching it and
    logging, never letting a Telegram outage break the caller's own error
    handling (PRD.md §47: Telegram is an alert channel, "no será fuente de
    verdad").
    """

    def __init__(self, base_url: str, bot_token: str, chat_id: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds

    async def notify(self, text: str) -> None:
        async def _call() -> None:
            url = f"{self._base_url}/bot{self._bot_token}/sendMessage"
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(url, json={"chat_id": self._chat_id, "text": text})
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"Telegram notification timed out after {self._timeout_seconds}s"
                ) from exc

            if response.is_error:
                raise RuntimeError(f"Telegram rejected the notification ({response.status_code})")

        await traced_call(
            tool_name="TelegramNotifyTool",
            provider=_PROVIDER,
            operation="notify",
            request_summary=f"text_len={len(text)}",
            call=_call,
            error_type_of=lambda _exc: TELEGRAM_ERROR,
        )
