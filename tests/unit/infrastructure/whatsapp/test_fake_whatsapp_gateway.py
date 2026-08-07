import pytest

from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.whatsapp.fake_whatsapp_gateway import FakeWhatsAppGateway
from tests.fixtures.gateways import make_whatsapp_gateway


@pytest.mark.asyncio
async def test_send_text_message_returns_external_id_and_records_the_message():
    gateway = make_whatsapp_gateway()
    to = PhoneNumber("+5491122334455")

    external_id = await gateway.send_text_message(to, "Hola, tu turno es mañana")

    assert external_id == "fake-msg-1"
    assert gateway.sent_messages == [(to, "Hola, tu turno es mañana")]


@pytest.mark.asyncio
async def test_send_text_message_generates_unique_ids_across_calls():
    gateway = make_whatsapp_gateway()
    to = PhoneNumber("+5491122334455")

    first_id = await gateway.send_text_message(to, "first")
    second_id = await gateway.send_text_message(to, "second")

    assert first_id != second_id
    assert len(gateway.sent_messages) == 2


def test_fake_whatsapp_gateway_satisfies_messaging_gateway_protocol():
    assert isinstance(FakeWhatsAppGateway(), MessagingGateway)
