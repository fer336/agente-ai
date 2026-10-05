import random
import re

from app.agent.example_identity import (
    EXAMPLE_FULL_NAMES,
    pick_example_dni,
    pick_example_full_name,
    pick_example_identity,
)


def test_catalog_is_large_and_every_name_is_a_full_name() -> None:
    assert len(EXAMPLE_FULL_NAMES) >= 15
    assert len(set(EXAMPLE_FULL_NAMES)) == len(EXAMPLE_FULL_NAMES)
    assert all(len(name.split()) >= 2 for name in EXAMPLE_FULL_NAMES)


def test_pick_example_full_name_returns_a_catalog_name() -> None:
    assert pick_example_full_name() in EXAMPLE_FULL_NAMES


def test_pick_example_dni_is_a_plausible_seven_or_eight_digit_number() -> None:
    rng = random.Random(1)
    for _ in range(200):
        dni = pick_example_dni(rng)
        assert re.fullmatch(r"\d{7,8}", dni)
        assert not dni.startswith("0")


def test_seeded_rng_is_deterministic() -> None:
    first = pick_example_identity(random.Random(42))
    second = pick_example_identity(random.Random(42))

    assert first == second


def test_examples_vary_across_calls() -> None:
    rng = random.Random(7)
    identities = {pick_example_identity(rng) for _ in range(30)}

    assert len({name for name, _ in identities}) > 1
    assert len({dni for _, dni in identities}) > 1


def test_identity_is_name_and_dni_from_the_pools() -> None:
    name, dni = pick_example_identity(random.Random(3))

    assert name in EXAMPLE_FULL_NAMES
    assert re.fullmatch(r"\d{7,8}", dni)
