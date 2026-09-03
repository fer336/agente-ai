import dataclasses

import pytest

from app.domain.value_objects.dni import Dni


def test_accepts_an_8_digit_dni():
    dni = Dni(value="30123456")

    assert dni.value == "30123456"


def test_accepts_a_7_digit_dni():
    dni = Dni(value="5123456")

    assert dni.value == "5123456"


def test_accepts_a_dni_with_dots_and_normalizes_it():
    dni = Dni(value="30.123.456")

    assert dni.value == "30123456"
    assert str(dni) == "30123456"


def test_accepts_a_dni_with_surrounding_whitespace():
    dni = Dni(value="  30123456  ")

    assert dni.value == "30123456"


def test_dni_is_frozen():
    dni = Dni(value="30123456")

    with pytest.raises(dataclasses.FrozenInstanceError):
        dni.value = "1"  # type: ignore[misc]


def test_rejects_a_dni_with_letters():
    with pytest.raises(ValueError, match="Invalid DNI"):
        Dni(value="3012345A")


def test_rejects_a_dni_that_is_too_short():
    with pytest.raises(ValueError, match="Invalid DNI"):
        Dni(value="123456")


def test_rejects_a_dni_that_is_too_long():
    with pytest.raises(ValueError, match="Invalid DNI"):
        Dni(value="123456789")


def test_rejects_an_empty_value():
    with pytest.raises(ValueError, match="Invalid DNI"):
        Dni(value="")
