import pytest

from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.ycloud.handoff_gateway import YCloudHandoffGateway


class _StubYCloudClient:
    def __init__(self, contact: dict[str, object] | None = None) -> None:
        self.contact = contact
        self.find_calls: list[str] = []
        self.update_calls: list[tuple[str, list[str]]] = []

    async def find_contact_by_phone(self, phone: str) -> dict[str, object] | None:
        self.find_calls.append(phone)
        return self.contact

    async def update_contact_tags(self, contact_id: str, tags: list[str]) -> None:
        self.update_calls.append((contact_id, list(tags)))


@pytest.mark.asyncio
async def test_request_handoff_tags_the_contact_resolved_from_the_conversation_phone():
    client = _StubYCloudClient(contact={"id": "contact-1", "tags": ["vip"]})
    gateway = YCloudHandoffGateway(client)

    await gateway.request_handoff(
        ConversationId("ycloud-+5491122334455"), "patient requested a human"
    )

    assert client.find_calls == ["+5491122334455"]
    assert client.update_calls == [("contact-1", ["vip", "Human"])]


@pytest.mark.asyncio
async def test_request_handoff_does_not_duplicate_an_existing_humano_tag():
    client = _StubYCloudClient(contact={"id": "contact-1", "tags": ["Human"]})
    gateway = YCloudHandoffGateway(client)

    await gateway.request_handoff(ConversationId("ycloud-+5491122334455"), "reason")

    assert client.update_calls == []


@pytest.mark.asyncio
async def test_request_handoff_no_ops_when_contact_cannot_be_resolved():
    client = _StubYCloudClient(contact=None)
    gateway = YCloudHandoffGateway(client)

    await gateway.request_handoff(ConversationId("ycloud-+5491122334455"), "reason")

    assert client.update_calls == []


@pytest.mark.asyncio
async def test_request_handoff_no_ops_when_contact_has_no_id():
    client = _StubYCloudClient(contact={"tags": []})
    gateway = YCloudHandoffGateway(client)

    await gateway.request_handoff(ConversationId("ycloud-+5491122334455"), "reason")

    assert client.update_calls == []


def test_ycloud_handoff_gateway_satisfies_human_handoff_gateway_protocol():
    assert isinstance(YCloudHandoffGateway(_StubYCloudClient()), HumanHandoffGateway)
