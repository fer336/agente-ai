import dataclasses

import pytest

from app.domain.value_objects.conversation_id import ConversationId


def test_creates_conversation_id_from_non_empty_string():
    conversation_id = ConversationId(value="conv-123")

    assert conversation_id.value == "conv-123"


def test_conversation_id_is_frozen():
    conversation_id = ConversationId(value="conv-123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        conversation_id.value = "conv-999"  # type: ignore[misc]


def test_rejects_empty_conversation_id():
    with pytest.raises(ValueError, match="empty"):
        ConversationId(value="")


def test_rejects_whitespace_only_conversation_id():
    with pytest.raises(ValueError, match="empty"):
        ConversationId(value="   ")
