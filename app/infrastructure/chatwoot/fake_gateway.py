from itertools import count

from app.domain.value_objects.phone_number import PhoneNumber


class FakeChatwootGateway:
    """In-memory fake implementing `ChatwootGateway` for local dev and tests.

    Also a test-introspection surface: `sent_incoming`/`sent_outgoing`/
    `labels_by_conversation` let a test assert exactly what would have
    reached Chatwoot, without any real HTTP call.
    """

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self._contact_ids_by_phone: dict[str, str] = {}
        self._next_contact_id = count(1)
        self._next_conversation_id = count(1)
        self.sent_incoming: list[tuple[str, str]] = []
        self.sent_outgoing: list[tuple[str, str]] = []
        self.labels_by_conversation: dict[str, str] = {}

    async def find_or_create_contact(self, phone: PhoneNumber, name: str) -> tuple[str, str]:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        key = str(phone)
        contact_id = self._contact_ids_by_phone.get(key)
        if contact_id is None:
            contact_id = str(next(self._next_contact_id))
            self._contact_ids_by_phone[key] = contact_id
        return contact_id, f"source-{contact_id}"

    async def create_conversation(self, source_id: str, contact_id: str) -> str:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        return str(next(self._next_conversation_id))

    async def post_incoming_message(self, chatwoot_conversation_id: str, text: str) -> None:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        self.sent_incoming.append((chatwoot_conversation_id, text))

    async def post_outgoing_message(self, chatwoot_conversation_id: str, text: str) -> None:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        self.sent_outgoing.append((chatwoot_conversation_id, text))

    async def has_administracion_label(self, chatwoot_conversation_id: str) -> bool:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        return self.labels_by_conversation.get(chatwoot_conversation_id) == "administracion"

    async def assign_administracion(self, chatwoot_conversation_id: str) -> None:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        self.labels_by_conversation[chatwoot_conversation_id] = "administracion"

    async def assign_bot(self, chatwoot_conversation_id: str) -> None:
        if self._fail:
            raise RuntimeError("FakeChatwootGateway configured to fail")
        self.labels_by_conversation[chatwoot_conversation_id] = "agente"
