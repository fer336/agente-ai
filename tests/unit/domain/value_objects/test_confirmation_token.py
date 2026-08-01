import dataclasses

import pytest

from app.domain.value_objects.confirmation_token import ConfirmationToken


def test_creates_confirmation_token_from_non_empty_string():
    confirmation_token = ConfirmationToken(value="token-123")

    assert confirmation_token.value == "token-123"


def test_confirmation_token_is_frozen():
    confirmation_token = ConfirmationToken(value="token-123")

    with pytest.raises(dataclasses.FrozenInstanceError):
        confirmation_token.value = "token-999"  # type: ignore[misc]


def test_rejects_empty_confirmation_token():
    with pytest.raises(ValueError, match="empty"):
        ConfirmationToken(value="")


def test_rejects_whitespace_only_confirmation_token():
    with pytest.raises(ValueError, match="empty"):
        ConfirmationToken(value="   ")
