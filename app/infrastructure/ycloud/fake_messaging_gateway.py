from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber


class FakeYCloudMessagingGateway:
    """In-memory fake implementing `MessagingGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[PhoneNumber, str]] = []
        self.sent_buttons: list[tuple[PhoneNumber, str, list[InteractiveButton]]] = []
        self._next_id = 1

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        self.sent_messages.append((to, text))
        return self._next_external_id()

    async def send_buttons(
        self, to: PhoneNumber, text: str, buttons: list[InteractiveButton]
    ) -> str:
        self.sent_buttons.append((to, text, buttons))
        return self._next_external_id()

    def _next_external_id(self) -> str:
        external_id = f"fake-msg-{self._next_id}"
        self._next_id += 1
        return external_id
