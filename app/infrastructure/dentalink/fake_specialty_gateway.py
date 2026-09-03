from app.domain.entities.specialty import Specialty


class FakeSpecialtyGateway:
    """In-memory fake implementing `SpecialtyGateway` for local dev and tests."""

    def __init__(self, specialties: list[Specialty] | None = None) -> None:
        self._specialties = list(specialties) if specialties else []

    async def list_specialties(self) -> list[Specialty]:
        return list(self._specialties)
