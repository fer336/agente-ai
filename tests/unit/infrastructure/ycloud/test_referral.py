import json

import pytest

from app.infrastructure.ycloud.referral import MAX_RAW_BYTES, normalize_referral

_META_SHAPE = {
    "source_url": "https://fb.me/abc",
    "source_id": "120239003788760630",
    "source_type": "ad",
    "headline": "Limpieza dental",
    "body": "Agenda hoy",
    "media_type": "image",
    "image_url": "https://example.com/i.jpg",
    "ctwa_clid": "AR123",
}


def test_meta_shape_is_normalized():
    result = normalize_referral(_META_SHAPE)

    assert result is not None
    assert result.source_id == "120239003788760630"
    assert result.source_type == "ad"
    assert result.source_url == "https://fb.me/abc"
    assert result.headline == "Limpieza dental"
    assert result.body == "Agenda hoy"
    assert result.media_type == "image"
    assert result.ctwa_clid == "AR123"
    assert result.raw["image_url"] == "https://example.com/i.jpg"


def test_camel_case_keys_are_accepted():
    result = normalize_referral(
        {"sourceId": "55", "sourceType": "post", "sourceUrl": "u", "ctwaClid": "c"}
    )

    assert result is not None
    assert (result.source_id, result.source_type, result.source_url, result.ctwa_clid) == (
        "55",
        "post",
        "u",
        "c",
    )


@pytest.mark.parametrize("key", ["ad_id", "adId"])
def test_ad_id_aliases_fill_source_id(key):
    result = normalize_referral({key: "777"})

    assert result is not None
    assert result.source_id == "777"


def test_numeric_source_id_becomes_a_string():
    result = normalize_referral({"source_id": 120239003788760630})

    assert result is not None
    assert result.source_id == "120239003788760630"


def test_source_id_takes_precedence_over_aliases():
    result = normalize_referral({"ad_id": "2", "source_id": "1"})

    assert result is not None
    assert result.source_id == "1"


def test_blank_values_are_treated_as_missing():
    result = normalize_referral({"source_id": "   ", "ad_id": "9", "headline": ""})

    assert result is not None
    assert result.source_id == "9"
    assert result.headline is None


def test_missing_known_fields_still_keeps_raw():
    result = normalize_referral({"something_new": {"a": 1}})

    assert result is not None
    assert result.source_id is None
    assert result.raw == {"something_new": {"a": 1}}


@pytest.mark.parametrize("garbage", [None, "", "ad", 5, 1.5, [], [1, 2], {}, True])
def test_garbage_returns_none(garbage):
    assert normalize_referral(garbage) is None


def test_huge_strings_are_dropped_from_raw_but_normalized_fields_survive():
    result = normalize_referral({"source_id": "1", "blob": "x" * 100_000})

    assert result is not None
    assert result.source_id == "1"
    assert "blob" not in result.raw


def test_oversized_raw_is_replaced_by_a_marker_and_stays_bounded():
    huge = {"source_id": "1", **{f"k{i}": "y" * 500 for i in range(100)}}

    result = normalize_referral(huge)

    assert result is not None
    assert result.source_id == "1"
    assert len(json.dumps(result.raw).encode()) <= MAX_RAW_BYTES
    assert result.raw.get("_truncated") is True


def test_deeply_nested_input_does_not_raise():
    nested: dict[str, object] = {"source_id": "1"}
    cursor = nested
    for _ in range(500):
        child: dict[str, object] = {}
        cursor["n"] = child
        cursor = child

    result = normalize_referral(nested)

    assert result is not None
    assert result.source_id == "1"
    assert len(json.dumps(result.raw).encode()) <= MAX_RAW_BYTES


def test_non_json_values_in_raw_are_stringified():
    result = normalize_referral({"source_id": "1", "weird": {1, 2}, "obj": object})

    assert result is not None
    json.dumps(result.raw)
