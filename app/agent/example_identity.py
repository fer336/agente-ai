"""Fictional name/DNI examples shown to the patient when asking for their data.

A fixed example ("Rosa Gómez, 30123456") made every ask read the same and, worse, led
patients to copy it. The helpers here pick a fresh one per message. The names are common
Argentine given names with varied surnames, deliberately neutral and not tied to any
real or famous person.
"""

import random

EXAMPLE_FULL_NAMES = (
    "Rosa Gómez",
    "Laura Fernández",
    "Marta Benítez",
    "Carolina Ruiz",
    "Silvia Domínguez",
    "Julieta Acosta",
    "Mariana Sosa",
    "Valeria Medina",
    "Lucía Herrera",
    "Natalia Peralta",
    "Carlos Méndez",
    "Martín Ledesma",
    "Diego Rojas",
    "Pablo Giménez",
    "Sergio Villalba",
    "Gustavo Ortiz",
    "Federico Aguirre",
    "Hernán Cabrera",
    "Javier Molina",
    "Matías Quiroga",
)

#: Realistic DNI range (7 or 8 digits, never a leading zero).
_MIN_EXAMPLE_DNI = 5_000_000
_MAX_EXAMPLE_DNI = 49_999_999


def pick_example_full_name(rng: random.Random | None = None) -> str:
    return (rng or random).choice(EXAMPLE_FULL_NAMES)


def pick_example_dni(rng: random.Random | None = None) -> str:
    return str((rng or random).randint(_MIN_EXAMPLE_DNI, _MAX_EXAMPLE_DNI))


def pick_example_identity(rng: random.Random | None = None) -> tuple[str, str]:
    """A fictional `(full_name, dni)` pair; pass a seeded `Random` for determinism."""
    return pick_example_full_name(rng), pick_example_dni(rng)
