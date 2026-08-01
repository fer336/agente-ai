import dataclasses

import pytest

from app.domain.value_objects.idempotency_key import IdempotencyKey


def test_creates_idempotency_key_from_non_empty_string():
    idempotency_key = IdempotencyKey(value="create:conversation-123:pending-action-456")

    assert idempotency_key.value == "create:conversation-123:pending-action-456"


def test_idempotency_key_is_frozen():
    idempotency_key = IdempotencyKey(value="create:conversation-123:pending-action-456")

    with pytest.raises(dataclasses.FrozenInstanceError):
        idempotency_key.value = "other"  # type: ignore[misc]


def test_rejects_empty_idempotency_key():
    with pytest.raises(ValueError, match="empty"):
        IdempotencyKey(value="")


def test_rejects_whitespace_only_idempotency_key():
    with pytest.raises(ValueError, match="empty"):
        IdempotencyKey(value="   ")
