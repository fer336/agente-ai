from app.domain.value_objects.phone_number import PhoneNumber


class FakeWhatsAppGateway:
    """In-memory fake implementing `MessagingGateway` for local dev and tests."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[PhoneNumber, str]] = []
        self._next_id = 1

    async def send_text_message(self, to: PhoneNumber, text: str) -> str:
        self.sent_messages.append((to, text))
        external_id = f"fake-msg-{self._next_id}"
        self._next_id += 1
        return external_id
