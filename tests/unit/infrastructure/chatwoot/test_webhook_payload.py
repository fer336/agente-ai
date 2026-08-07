import pytest

from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.chatwoot.webhook_payload import ChatwootMessageCreatedPayload
from tests.fixtures.seed_objects import make_chatwoot_payload


def test_to_inbound_message_dto_maps_source_id_phone_and_content():
    payload = ChatwootMessageCreatedPayload.model_validate(make_chatwoot_payload())

    dto = payload.to_inbound_message_dto()

    assert dto.external_message_id == "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5"
    assert dto.chatwoot_conversation_id == "100"
    assert dto.from_phone == PhoneNumber("+5491122334455")
    assert dto.text == "Hola, quiero agendar un turno"


def test_to_inbound_message_dto_maps_a_different_payload_to_different_values():
    raw = make_chatwoot_payload(
        source_id="wamid.OTHER",
        content="Necesito reagendar",
        sender={"phone_number": "+5491100000000"},
        conversation={"id": 777},
    )
    payload = ChatwootMessageCreatedPayload.model_validate(raw)

    dto = payload.to_inbound_message_dto()

    assert dto.external_message_id == "wamid.OTHER"
    assert dto.chatwoot_conversation_id == "777"
    assert dto.from_phone == PhoneNumber("+5491100000000")
    assert dto.text == "Necesito reagendar"


def test_to_inbound_message_dto_raises_when_sender_phone_number_is_missing():
    raw = make_chatwoot_payload(sender={})
    payload = ChatwootMessageCreatedPayload.model_validate(raw)

    with pytest.raises(ValueError):
        payload.to_inbound_message_dto()


def test_to_inbound_message_dto_raises_when_source_id_is_missing():
    raw = make_chatwoot_payload(source_id="")
    payload = ChatwootMessageCreatedPayload.model_validate(raw)

    with pytest.raises(ValueError):
        payload.to_inbound_message_dto()


def test_to_inbound_message_dto_raises_when_source_id_is_whitespace_only():
    # `source_id="   "` is truthy, so the falsy-only guard let it through
    # while `ExternalMessageId.__post_init__` rejects it via `.strip()` —
    # the guard must match that invariant exactly.
    raw = make_chatwoot_payload(source_id="   ")
    payload = ChatwootMessageCreatedPayload.model_validate(raw)

    with pytest.raises(ValueError):
        payload.to_inbound_message_dto()


def test_to_inbound_message_dto_raises_when_sender_phone_number_is_whitespace_only():
    raw = make_chatwoot_payload(sender={"phone_number": "   "})
    payload = ChatwootMessageCreatedPayload.model_validate(raw)

    with pytest.raises(ValueError):
        payload.to_inbound_message_dto()
