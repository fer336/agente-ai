import pytest

from app.infrastructure.ycloud.schemas import YCloudInboundEventPayload
from app.infrastructure.ycloud.webhook_parser import is_processable_message, to_inbound_message_dto
from tests.fixtures.seed_objects import make_ycloud_payload

_REFERRAL = {
    "source_id": "120239003788760630",
    "source_type": "ad",
    "source_url": "https://fb.me/abc",
    "headline": "Limpieza dental",
    "ctwa_clid": "AR123",
}


def _payload_with(**message_extra: object) -> YCloudInboundEventPayload:
    raw = make_ycloud_payload()
    raw["whatsappInboundMessage"].update(message_extra)  # type: ignore[union-attr]
    return YCloudInboundEventPayload.model_validate(raw)


def test_referral_is_mapped_to_the_dto():
    dto = to_inbound_message_dto(_payload_with(referral=_REFERRAL))

    assert dto.referral is not None
    assert dto.referral.source_id == "120239003788760630"
    assert dto.referral.ctwa_clid == "AR123"
    assert dto.referral.raw["headline"] == "Limpieza dental"


def test_missing_referral_leaves_the_dto_field_empty():
    dto = to_inbound_message_dto(_payload_with())

    assert dto.referral is None


@pytest.mark.parametrize("garbage", ["ad", 5, [1, 2], True, {}])
def test_non_dict_or_empty_referral_never_drops_the_message(garbage):
    payload = _payload_with(referral=garbage)

    assert is_processable_message(payload, "") is True
    assert to_inbound_message_dto(payload).referral is None


def test_referral_nested_under_context_is_used_when_top_level_is_absent():
    dto = to_inbound_message_dto(_payload_with(context={"referral": _REFERRAL}))

    assert dto.referral is not None
    assert dto.referral.source_id == "120239003788760630"


def test_top_level_referral_wins_over_context_referral():
    dto = to_inbound_message_dto(
        _payload_with(referral={"source_id": "top"}, context={"referral": {"source_id": "ctx"}})
    )

    assert dto.referral is not None
    assert dto.referral.source_id == "top"


def test_non_dict_context_never_drops_the_message():
    payload = _payload_with(context="weird")

    assert is_processable_message(payload, "") is True
    assert to_inbound_message_dto(payload).referral is None


def test_referral_is_kept_on_an_audio_message_too():
    raw = make_ycloud_payload()
    message = raw["whatsappInboundMessage"]
    message.update(  # type: ignore[union-attr]
        {"type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg"}, "referral": _REFERRAL}
    )
    dto = to_inbound_message_dto(YCloudInboundEventPayload.model_validate(raw))

    assert dto.message_type == "audio"
    assert dto.referral is not None
