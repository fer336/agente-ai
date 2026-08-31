class FakeTelegramAlertNotifier:
    """In-memory fake implementing `AlertNotifier` for local dev and tests."""

    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent_messages.append(text)
