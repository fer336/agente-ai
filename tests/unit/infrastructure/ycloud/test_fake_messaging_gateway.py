import pytest

from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import make_ycloud_messaging_gateway


@pytest.mark.asyncio
async def test_send_text_message_records_recipient_and_text_and_returns_unique_ids():
    gateway = make_ycloud_messaging_gateway()

    first_id = await gateway.send_text_message(PhoneNumber("+5491122334455"), "Hola")
    second_id = await gateway.send_text_message(PhoneNumber("+5491100000000"), "Chau")

    assert gateway.sent_messages == [
        (PhoneNumber("+5491122334455"), "Hola"),
        (PhoneNumber("+5491100000000"), "Chau"),
    ]
    assert first_id != second_id


@pytest.mark.asyncio
async def test_send_buttons_records_recipient_text_and_buttons():
    gateway = make_ycloud_messaging_gateway()
    buttons = [InteractiveButton(id="confirm", title="Confirmar")]

    await gateway.send_buttons(PhoneNumber("+5491122334455"), "¿Confirmás?", buttons)

    assert gateway.sent_buttons == [(PhoneNumber("+5491122334455"), "¿Confirmás?", buttons)]


def test_fake_ycloud_messaging_gateway_satisfies_messaging_gateway_protocol():
    assert isinstance(FakeYCloudMessagingGateway(), MessagingGateway)
