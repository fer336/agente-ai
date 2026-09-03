import pytest

from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.schemas import (
    YCloudContactAttributesChangedEventPayload,
    YCloudInboundEventPayload,
)
from app.infrastructure.ycloud.webhook_parser import (
    extract_tag_mode_change,
    is_processable_message,
    is_tag_mode_change_event,
    to_inbound_message_dto,
)
from tests.fixtures.seed_objects import (
    make_ycloud_audio_payload,
    make_ycloud_button_reply_payload,
    make_ycloud_payload,
    make_ycloud_tag_change_payload,
)

_WHATSAPP_NUMBER = "+5491100000001"


def test_is_processable_message_accepts_matching_text_message():
    payload = YCloudInboundEventPayload.model_validate(make_ycloud_payload())

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is True


def test_is_processable_message_rejects_wrong_event_type():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_payload(type="whatsapp.message.delivered")
    )

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_is_processable_message_accepts_an_audio_message_with_a_media_id():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_audio_payload(whatsapp_number=_WHATSAPP_NUMBER)
    )

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is True


def test_is_processable_message_rejects_an_audio_message_with_no_media_id():
    raw = make_ycloud_audio_payload(whatsapp_number=_WHATSAPP_NUMBER)
    raw["whatsappInboundMessage"]["audio"]["id"] = ""
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_is_processable_message_rejects_an_audio_message_with_no_audio_object():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["type"] = "audio"

    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_is_processable_message_rejects_mismatched_whatsapp_number():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["to"] = "+5491199999999"
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_is_processable_message_skips_number_check_when_not_configured():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["to"] = "+5491199999999"
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, "") is True


def test_is_processable_message_accepts_a_button_reply():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_button_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    )

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is True


def test_is_processable_message_rejects_interactive_message_missing_button_reply():
    raw = make_ycloud_button_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    raw["whatsappInboundMessage"]["interactive"] = {"type": "button_reply", "button_reply": None}
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_is_processable_message_rejects_non_button_reply_interactive_type():
    raw = make_ycloud_button_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    raw["whatsappInboundMessage"]["interactive"]["type"] = "list_reply"
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_to_inbound_message_dto_maps_id_phone_and_text():
    payload = YCloudInboundEventPayload.model_validate(make_ycloud_payload())

    dto = to_inbound_message_dto(payload)

    assert dto.external_message_id == "wamid.HBgLNTQ5MTEyMjMzNDQ1FQIAERgSMkQ5"
    assert dto.from_phone == PhoneNumber("+5491122334455")
    assert dto.text == "Hola, quiero agendar un turno"
    assert dto.button_payload is None


def test_to_inbound_message_dto_maps_a_different_payload_to_different_values():
    raw = make_ycloud_payload(
        whatsappInboundMessage={
            "id": "wamid.OTHER",
            "from": "+5491100000000",
            "to": _WHATSAPP_NUMBER,
            "type": "text",
            "text": {"body": "Necesito reagendar"},
        }
    )
    payload = YCloudInboundEventPayload.model_validate(raw)

    dto = to_inbound_message_dto(payload)

    assert dto.external_message_id == "wamid.OTHER"
    assert dto.from_phone == PhoneNumber("+5491100000000")
    assert dto.text == "Necesito reagendar"


def test_to_inbound_message_dto_maps_a_button_reply_to_its_payload_and_title():
    raw = make_ycloud_button_reply_payload(
        whatsapp_number=_WHATSAPP_NUMBER,
        button_id="CONFIRM_APPOINTMENT",
        button_title="✅ Confirmar",
    )
    payload = YCloudInboundEventPayload.model_validate(raw)

    dto = to_inbound_message_dto(payload)

    assert dto.button_payload == "CONFIRM_APPOINTMENT"
    assert dto.text == "✅ Confirmar"


def test_to_inbound_message_dto_prepends_plus_when_from_lacks_it():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["from"] = "5491122334455"
    payload = YCloudInboundEventPayload.model_validate(raw)

    dto = to_inbound_message_dto(payload)

    assert dto.from_phone == PhoneNumber("+5491122334455")


def test_to_inbound_message_dto_raises_when_from_is_missing():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["from"] = ""
    payload = YCloudInboundEventPayload.model_validate(raw)

    with pytest.raises(ValueError):
        to_inbound_message_dto(payload)


def test_to_inbound_message_dto_raises_when_id_is_missing():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["id"] = ""
    payload = YCloudInboundEventPayload.model_validate(raw)

    with pytest.raises(ValueError):
        to_inbound_message_dto(payload)


def test_to_inbound_message_dto_raises_when_id_is_whitespace_only():
    # `id="   "` is truthy, so a falsy-only guard would let it through
    # while `ExternalMessageId.__post_init__` rejects it via `.strip()` —
    # the guard must match that invariant exactly.
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["id"] = "   "
    payload = YCloudInboundEventPayload.model_validate(raw)

    with pytest.raises(ValueError):
        to_inbound_message_dto(payload)


def test_to_inbound_message_dto_maps_audio_metadata_with_no_text():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_audio_payload(media_id="media-1", mime_type="audio/ogg", sha256="abc123")
    )

    dto = to_inbound_message_dto(payload)

    assert dto.message_type == "audio"
    assert dto.text == ""
    assert dto.button_payload is None
    assert dto.media_id == "media-1"
    assert dto.media_mime_type == "audio/ogg"
    assert dto.media_sha256 == "abc123"


def test_to_inbound_message_dto_maps_audio_with_no_sha256():
    payload = YCloudInboundEventPayload.model_validate(make_ycloud_audio_payload())

    dto = to_inbound_message_dto(payload)

    assert dto.media_sha256 is None


def test_to_inbound_message_dto_raises_when_from_is_whitespace_only():
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"]["from"] = "   "
    payload = YCloudInboundEventPayload.model_validate(raw)

    with pytest.raises(ValueError):
        to_inbound_message_dto(payload)


def test_is_tag_mode_change_event_accepts_contact_attributes_changed():
    assert is_tag_mode_change_event("contact.attributes_changed") is True


def test_is_tag_mode_change_event_rejects_other_types():
    assert is_tag_mode_change_event("whatsapp.inbound_message.received") is False


def test_extract_tag_mode_change_maps_habla_agente_to_agent_mode():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(contact_id="c-1", tag_value="Agente")
    )

    assert extract_tag_mode_change(payload) == ("c-1", "agent")


def test_extract_tag_mode_change_maps_habla_humano_to_human_mode():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(contact_id="c-1", tag_value="Humano")
    )

    assert extract_tag_mode_change(payload) == ("c-1", "human")


def test_extract_tag_mode_change_ignores_unrelated_tags():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(tag_value="vip")
    )

    assert extract_tag_mode_change(payload) is None


def test_extract_tag_mode_change_ignores_removed_action():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(tag_value="Agente", action="REMOVED")
    )

    assert extract_tag_mode_change(payload) is None


def test_extract_tag_mode_change_returns_none_when_no_tags_changed():
    raw = make_ycloud_tag_change_payload()
    raw["contactAttributesChanged"]["changedAttributes"] = {}
    payload = YCloudContactAttributesChangedEventPayload.model_validate(raw)

    assert extract_tag_mode_change(payload) is None


def test_extract_tag_mode_change_returns_none_when_contact_id_missing():
    raw = make_ycloud_tag_change_payload(contact_id="")
    payload = YCloudContactAttributesChangedEventPayload.model_validate(raw)

    assert extract_tag_mode_change(payload) is None
