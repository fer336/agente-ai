import pytest

from app.domain.repositories.gateways import (
    MessagingGateway,
    TemplateMessage,
    TemplateQuickReplyButton,
)
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import make_ycloud_messaging_gateway


@pytest.mark.asyncio
async def test_send_template_records_recipient_and_structured_template():
    gateway = make_ycloud_messaging_gateway()
    template = TemplateMessage(
        name="recordatorio_turno_confirmar",
        language="es_AR",
        body_parameters=("Ana",),
        quick_reply_buttons=(TemplateQuickReplyButton(index=0, payload="CONFIRM"),),
    )

    external_id = await gateway.send_template(PhoneNumber("+5491122334455"), template)

    assert gateway.sent_templates == [(PhoneNumber("+5491122334455"), template)]
    assert external_id == "fake-msg-1"


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

    assert gateway.sent_buttons == [(PhoneNumber("+5491122334455"), "¿Confirmás?", buttons, None)]


@pytest.mark.asyncio
async def test_send_buttons_records_the_image_url_when_given():
    gateway = make_ycloud_messaging_gateway()
    buttons = [InteractiveButton(id="confirm", title="Confirmar")]

    await gateway.send_buttons(
        PhoneNumber("+5491122334455"), "¡Hola!", buttons, image_url="https://example.com/logo.png"
    )

    assert gateway.sent_buttons == [
        (
            PhoneNumber("+5491122334455"),
            "¡Hola!",
            buttons,
            "https://example.com/logo.png",
        )
    ]


def test_fake_ycloud_messaging_gateway_satisfies_messaging_gateway_protocol():
    assert isinstance(FakeYCloudMessagingGateway(), MessagingGateway)


@pytest.mark.asyncio
async def test_get_contact_phone_returns_preset_phone_or_none():
    gateway = make_ycloud_messaging_gateway()
    gateway.contact_phones["contact-1"] = PhoneNumber("+5491122334455")

    assert await gateway.get_contact_phone("contact-1") == PhoneNumber("+5491122334455")
    assert await gateway.get_contact_phone("unknown") is None
