"""Tolerant extraction of the Click-to-WhatsApp `referral` object.

Meta attaches `referral` to the first inbound message of a lead that clicked a
Facebook/Instagram ad. YCloud's exact JSON nesting and key casing are NOT
verified against a live delivery (most likely it mirrors Meta's snake_case
under `whatsappInboundMessage.referral`), so this module never raises on an
unexpected shape: it pulls the fields we attribute on from the known aliases
and keeps a bounded copy of the raw object so the real shape can be learned
from the first real ad message.
"""

import json

from app.application.messages.inbound_message_dto import AdReferralDTO

#: Upper bound for the serialized raw copy kept in the database.
MAX_RAW_BYTES = 8 * 1024
#: Strings longer than this are dropped from the raw copy (e.g. inlined blobs).
_MAX_RAW_STRING_LENGTH = 2048
#: Normalized text fields are cut to this length (they get their own columns).
_MAX_FIELD_LENGTH = 1000
_MAX_DEPTH = 4
_MAX_LIST_ITEMS = 50
_MAX_MARKER_KEYS = 50
_MAX_MARKER_KEY_LENGTH = 64

_SOURCE_ID_KEYS = ("source_id", "sourceId", "ad_id", "adId")
_SOURCE_TYPE_KEYS = ("source_type", "sourceType")
_SOURCE_URL_KEYS = ("source_url", "sourceUrl")
_HEADLINE_KEYS = ("headline",)
_BODY_KEYS = ("body",)
_CTWA_CLID_KEYS = ("ctwa_clid", "ctwaClid")
_MEDIA_TYPE_KEYS = ("media_type", "mediaType")

#: Sentinel for "drop this value from the raw copy".
_DROP = object()


def normalize_referral(raw: object) -> AdReferralDTO | None:
    """Builds an `AdReferralDTO` from a raw referral value, or `None` when the
    value is not a non-empty mapping (nothing usable to attribute or learn from)."""
    if not isinstance(raw, dict) or not raw:
        return None
    return AdReferralDTO(
        source_id=_first_text(raw, _SOURCE_ID_KEYS),
        source_type=_first_text(raw, _SOURCE_TYPE_KEYS),
        source_url=_first_text(raw, _SOURCE_URL_KEYS),
        headline=_first_text(raw, _HEADLINE_KEYS),
        body=_first_text(raw, _BODY_KEYS),
        ctwa_clid=_first_text(raw, _CTWA_CLID_KEYS),
        media_type=_first_text(raw, _MEDIA_TYPE_KEYS),
        raw=_bounded_raw(raw),
    )


def _first_text(raw: dict[object, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_FIELD_LENGTH]
    return None


def _bounded_raw(raw: dict[object, object]) -> dict[str, object]:
    sanitized = _sanitize(raw, 0)
    result = sanitized if isinstance(sanitized, dict) else {}
    if _serialized_size(result) <= MAX_RAW_BYTES:
        return result
    return {
        "_truncated": True,
        "keys": [str(key)[:_MAX_MARKER_KEY_LENGTH] for key in list(raw)[:_MAX_MARKER_KEYS]],
    }


def _sanitize(value: object, depth: int) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _DROP if len(value) > _MAX_RAW_STRING_LENGTH else value
    if depth >= _MAX_DEPTH:
        return _DROP
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            sanitized = _sanitize(item, depth + 1)
            if sanitized is not _DROP:
                cleaned[str(key)] = sanitized
        return cleaned
    if isinstance(value, list | tuple):
        items = (_sanitize(item, depth + 1) for item in list(value)[:_MAX_LIST_ITEMS])
        return [item for item in items if item is not _DROP]
    return str(value)[:_MAX_RAW_STRING_LENGTH]


def _serialized_size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        return MAX_RAW_BYTES + 1
