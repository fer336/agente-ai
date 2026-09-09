import pytest

from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.ycloud.schemas import (
    YCloudContactAttributesChangedEventPayload,
    YCloudInboundEventPayload,
    YCloudSmbMessageEchoEventPayload,
)
from app.infrastructure.ycloud.webhook_parser import (
    FLOW_RESPONSE_PAYLOAD_PREFIX,
    extract_bot_reactivation_command,
    extract_smb_echo_patient_phone,
    extract_tag_mode_change,
    is_processable_message,
    is_smb_message_echo_event,
    is_tag_mode_change_event,
    to_inbound_message_dto,
)
from tests.fixtures.seed_objects import (
    make_ycloud_audio_payload,
    make_ycloud_button_reply_payload,
    make_ycloud_list_reply_payload,
    make_ycloud_nfm_reply_payload,
    make_ycloud_payload,
    make_ycloud_smb_echo_payload,
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


def test_is_processable_message_accepts_a_completed_flow_reply():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_nfm_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    )

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is True


def test_is_processable_message_rejects_interactive_message_missing_nfm_reply():
    raw = make_ycloud_nfm_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    raw["whatsappInboundMessage"]["interactive"] = {"type": "nfm_reply", "nfm_reply": None}
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_to_inbound_message_dto_maps_a_completed_flow_reply_to_a_prefixed_payload():
    raw = make_ycloud_nfm_reply_payload(
        whatsapp_number=_WHATSAPP_NUMBER,
        response_json='{"full_name": "Rosa Gomez", "dni": "30123456"}',
    )
    payload = YCloudInboundEventPayload.model_validate(raw)

    dto = to_inbound_message_dto(payload)

    assert dto.button_payload == (
        f'{FLOW_RESPONSE_PAYLOAD_PREFIX}{{"full_name": "Rosa Gomez", "dni": "30123456"}}'
    )
    assert dto.text


def test_is_processable_message_accepts_a_list_reply():
    payload = YCloudInboundEventPayload.model_validate(
        make_ycloud_list_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    )

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is True


def test_is_processable_message_rejects_interactive_message_missing_list_reply():
    raw = make_ycloud_list_reply_payload(whatsapp_number=_WHATSAPP_NUMBER)
    raw["whatsappInboundMessage"]["interactive"] = {"type": "list_reply", "list_reply": None}
    payload = YCloudInboundEventPayload.model_validate(raw)

    assert is_processable_message(payload, _WHATSAPP_NUMBER) is False


def test_to_inbound_message_dto_maps_a_list_reply_to_its_row_id_and_title():
    raw = make_ycloud_list_reply_payload(
        whatsapp_number=_WHATSAPP_NUMBER, row_id="MENU_CREATE", row_title="Agendar una cita"
    )
    payload = YCloudInboundEventPayload.model_validate(raw)

    dto = to_inbound_message_dto(payload)

    assert dto.button_payload == "MENU_CREATE"
    assert dto.text == "Agendar una cita"


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


def test_extract_tag_mode_change_maps_humano_added_to_human_mode():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(contact_id="c-1", tag_value="Human", action="ADDED")
    )

    assert extract_tag_mode_change(payload) == ("c-1", "human")


def test_extract_tag_mode_change_maps_humano_removed_to_agent_mode():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(contact_id="c-1", tag_value="Human", action="REMOVED")
    )

    assert extract_tag_mode_change(payload) == ("c-1", "agent")


def test_extract_tag_mode_change_ignores_unrelated_tags():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(tag_value="vip")
    )

    assert extract_tag_mode_change(payload) is None


def test_extract_tag_mode_change_ignores_unrelated_tag_being_removed():
    payload = YCloudContactAttributesChangedEventPayload.model_validate(
        make_ycloud_tag_change_payload(tag_value="vip", action="REMOVED")
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


def test_is_smb_message_echo_event_accepts_matching_type():
    assert is_smb_message_echo_event("whatsapp.smb.message.echoes") is True


def test_is_smb_message_echo_event_rejects_other_types():
    assert is_smb_message_echo_event("whatsapp.inbound_message.received") is False


def test_extract_smb_echo_patient_phone_returns_to_phone():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(patient_phone="+549****4455")
    )

    assert extract_smb_echo_patient_phone(payload) == "+549****4455"


def test_extract_smb_echo_patient_phone_adds_leading_plus_when_missing():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(patient_phone="549****4455")
    )

    assert extract_smb_echo_patient_phone(payload) == "+549****4455"


def test_extract_smb_echo_patient_phone_returns_none_when_missing():
    raw = make_ycloud_smb_echo_payload()
    raw["whatsappMessage"]["to"] = ""
    payload = YCloudSmbMessageEchoEventPayload.model_validate(raw)

    assert extract_smb_echo_patient_phone(payload) is None


def test_extract_smb_echo_patient_phone_returns_none_when_whitespace_only():
    raw = make_ycloud_smb_echo_payload()
    raw["whatsappMessage"]["to"] = "   "
    payload = YCloudSmbMessageEchoEventPayload.model_validate(raw)

    assert extract_smb_echo_patient_phone(payload) is None


def test_extract_bot_reactivation_command_matches_exact_lowercase():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(patient_phone="+549****4455", text_body="/bot")
    )

    assert extract_bot_reactivation_command(payload) == "+549****4455"


def test_extract_bot_reactivation_command_is_case_insensitive_and_trims():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(text_body="  /BoT  ")
    )

    assert extract_bot_reactivation_command(payload) == "+549****4455"


def test_extract_bot_reactivation_command_returns_none_for_other_text():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(text_body="Hola, ya te ayudo")
    )

    assert extract_bot_reactivation_command(payload) is None


def test_extract_bot_reactivation_command_returns_none_for_non_text_message():
    payload = YCloudSmbMessageEchoEventPayload.model_validate(
        make_ycloud_smb_echo_payload(message_type="image")
    )

    assert extract_bot_reactivation_command(payload) is None
