from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber


class FakeYCloudMessagingGateway:
    """In-memory fake implementing `MessagingGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[PhoneNumber, str]] = []
        self.sent_buttons: list[
            tuple[PhoneNumber, str, list[InteractiveButton], str | None]
        ] = []
        self.contact_phones: dict[str, PhoneNumber] = {}
        self.typing_indicators_sent: list[str] = []
        self._next_id = 1

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        self.sent_messages.append((to, text))
        return self._next_external_id()

    async def send_buttons(
        self,
        to: PhoneNumber,
        text: str,
        buttons: list[InteractiveButton],
        image_url: str | None = None,
    ) -> str:
        self.sent_buttons.append((to, text, buttons, image_url))
        return self._next_external_id()

    async def get_contact_phone(self, ycloud_contact_id: str) -> PhoneNumber | None:
        return self.contact_phones.get(ycloud_contact_id)

    async def send_typing_indicator(self, wamid: str) -> None:
        self.typing_indicators_sent.append(wamid)

    def _next_external_id(self) -> str:
        external_id = f"fake-msg-{self._next_id}"
        self._next_id += 1
        return external_id
