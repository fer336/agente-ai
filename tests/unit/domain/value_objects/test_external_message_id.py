import dataclasses

import pytest

from app.domain.value_objects.external_message_id import ExternalMessageId


def test_creates_external_message_id_from_non_empty_string():
    external_message_id = ExternalMessageId(value="wamid-123")

    assert external_message_id.value == "wamid-123"


def test_external_message_id_is_frozen():
    external_message_id = ExternalMessageId(value="wamid-123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        external_message_id.value = "wamid-999"  # type: ignore[misc]


def test_rejects_empty_external_message_id():
    with pytest.raises(ValueError, match="empty"):
        ExternalMessageId(value="")


def test_rejects_whitespace_only_external_message_id():
    with pytest.raises(ValueError, match="empty"):
        ExternalMessageId(value="   ")
