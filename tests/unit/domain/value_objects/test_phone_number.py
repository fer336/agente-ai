import dataclasses

import pytest

from app.domain.value_objects.phone_number import PhoneNumber


def test_creates_phone_number_from_valid_e164_string():
    phone = PhoneNumber(value="+5491122334455")

    assert phone.value == "+5491122334455"


def test_phone_number_is_frozen():
    phone = PhoneNumber(value="+5491122334455")

    with pytest.raises(dataclasses.FrozenInstanceError):
        phone.value = "+5491100000000"  # type: ignore[misc]


def test_rejects_phone_number_without_leading_plus():
    with pytest.raises(ValueError, match="E.164"):
        PhoneNumber(value="5491122334455")


def test_rejects_phone_number_with_non_digit_characters():
    with pytest.raises(ValueError, match="digits"):
        PhoneNumber(value="+549-1122334455")
