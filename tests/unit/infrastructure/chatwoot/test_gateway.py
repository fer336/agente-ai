import pytest

from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.exceptions import ChatwootAPIError
from app.infrastructure.chatwoot.gateway import ChatwootConversationGateway

_PHONE = PhoneNumber("+5491122334455")


class _StubChatwootClient:
    """Minimal double for `ChatwootClient`, exercising only the surface
    `ChatwootConversationGateway` actually calls — no real HTTP.
    """

    def __init__(
        self,
        create_contact_raises: ChatwootAPIError | None = None,
        existing_contact: dict[str, object] | None = None,
        labels_by_conversation: dict[str, list[str]] | None = None,
    ) -> None:
        self._create_contact_raises = create_contact_raises
        self._existing_contact = existing_contact
        self._labels_by_conversation = labels_by_conversation or {}
        self.create_contact_calls: list[tuple[str, str, str]] = []
        self.find_contact_calls: list[str] = []
        self.labels_set: list[tuple[str, list[str]]] = []
        self.get_labels_calls: list[str] = []

    async def create_contact(self, identifier: str, phone: str, name: str) -> dict[str, object]:
        self.create_contact_calls.append((identifier, phone, name))
        if self._create_contact_raises is not None:
            raise self._create_contact_raises
        return {
            "id": 99,
            "contact_inboxes": [{"source_id": "source-99"}],
        }

    async def find_contact_by_identifier(self, identifier: str) -> dict[str, object] | None:
        self.find_contact_calls.append(identifier)
        return self._existing_contact

    async def create_conversation(self, source_id: str, contact_id: str) -> str:
        return "chatwoot-conv-1"

    async def create_message(self, conversation_id: str, content: str, message_type: str) -> None:
        pass

    async def get_conversation_labels(self, conversation_id: str) -> list[str]:
        self.get_labels_calls.append(conversation_id)
        return list(self._labels_by_conversation.get(conversation_id, []))

    async def set_conversation_labels(self, conversation_id: str, labels: list[str]) -> None:
        self.labels_set.append((conversation_id, labels))


@pytest.mark.asyncio
async def test_find_or_create_contact_creates_a_new_contact_when_none_exists():
    client = _StubChatwootClient()
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    contact_id, source_id = await gateway.find_or_create_contact(_PHONE, "Juan Perez")

    assert contact_id == "99"
    assert source_id == "source-99"
    assert client.create_contact_calls == [(str(_PHONE), str(_PHONE), "Juan Perez")]
    assert client.find_contact_calls == []


@pytest.mark.asyncio
async def test_find_or_create_contact_falls_back_to_lookup_on_duplicate_422():
    # Confirmed live against the real Chatwoot instance: a duplicate
    # `identifier` returns 422 WITHOUT the existing contact in the body.
    existing_contact = {"id": 42, "contact_inboxes": [{"source_id": "source-42"}]}
    client = _StubChatwootClient(
        create_contact_raises=ChatwootAPIError("duplicate", status_code=422),
        existing_contact=existing_contact,
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    contact_id, source_id = await gateway.find_or_create_contact(_PHONE, "Juan Perez")

    assert contact_id == "42"
    assert source_id == "source-42"
    assert client.find_contact_calls == [str(_PHONE)]


@pytest.mark.asyncio
async def test_find_or_create_contact_reraises_a_non_422_api_error():
    client = _StubChatwootClient(
        create_contact_raises=ChatwootAPIError("server error", status_code=500)
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    with pytest.raises(ChatwootAPIError):
        await gateway.find_or_create_contact(_PHONE, "Juan Perez")


@pytest.mark.asyncio
async def test_find_or_create_contact_reraises_a_422_when_the_fallback_lookup_finds_nothing():
    # An unexpected 422 that isn't actually a duplicate-identifier case —
    # surfacing the original error beats silently returning garbage.
    client = _StubChatwootClient(
        create_contact_raises=ChatwootAPIError("duplicate", status_code=422),
        existing_contact=None,
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    with pytest.raises(ChatwootAPIError):
        await gateway.find_or_create_contact(_PHONE, "Juan Perez")


@pytest.mark.asyncio
async def test_assign_administracion_sets_the_administracion_label_when_none_exists():
    client = _StubChatwootClient()
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_administracion("chatwoot-conv-1")

    assert client.get_labels_calls == ["chatwoot-conv-1"]
    assert client.labels_set == [("chatwoot-conv-1", ["administracion"])]


@pytest.mark.asyncio
async def test_assign_bot_sets_the_agente_label_when_none_exists():
    client = _StubChatwootClient()
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_bot("chatwoot-conv-1")

    assert client.get_labels_calls == ["chatwoot-conv-1"]
    assert client.labels_set == [("chatwoot-conv-1", ["agente"])]


@pytest.mark.asyncio
async def test_assign_administracion_preserves_unrelated_labels_and_drops_agente():
    client = _StubChatwootClient(
        labels_by_conversation={"chatwoot-conv-1": ["vip", "agente", "urgent"]}
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_administracion("chatwoot-conv-1")

    assert client.labels_set == [("chatwoot-conv-1", ["vip", "urgent", "administracion"])]


@pytest.mark.asyncio
async def test_assign_bot_preserves_unrelated_labels_and_drops_administracion():
    client = _StubChatwootClient(
        labels_by_conversation={"chatwoot-conv-1": ["vip", "administracion", "urgent"]}
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_bot("chatwoot-conv-1")

    assert client.labels_set == [("chatwoot-conv-1", ["vip", "urgent", "agente"])]


@pytest.mark.asyncio
async def test_assign_administracion_skips_the_write_when_already_the_current_state():
    client = _StubChatwootClient(
        labels_by_conversation={"chatwoot-conv-1": ["vip", "administracion"]}
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_administracion("chatwoot-conv-1")

    assert client.labels_set == []


@pytest.mark.asyncio
async def test_assign_bot_skips_the_write_when_already_the_current_state():
    client = _StubChatwootClient(labels_by_conversation={"chatwoot-conv-1": ["vip", "agente"]})
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_bot("chatwoot-conv-1")

    assert client.labels_set == []


@pytest.mark.asyncio
async def test_assign_bot_removes_duplicate_labels_while_switching_control():
    client = _StubChatwootClient(
        labels_by_conversation={
            "chatwoot-conv-1": ["vip", "vip", "administracion", "administracion"]
        }
    )
    gateway = ChatwootConversationGateway(client)  # type: ignore[arg-type]

    await gateway.assign_bot("chatwoot-conv-1")

    assert client.labels_set == [("chatwoot-conv-1", ["vip", "agente"])]
