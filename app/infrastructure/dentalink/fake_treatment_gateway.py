from app.domain.entities.treatment import Treatment


class FakeTreatmentGateway:
    """In-memory fake implementing `TreatmentGateway` for local dev and tests."""

    def __init__(self, patient_treatments: dict[str, list[Treatment]] | None = None) -> None:
        self._patient_treatments = dict(patient_treatments) if patient_treatments else {}

    async def get_patient_treatments(self, patient_id: str) -> list[Treatment]:
        return list(self._patient_treatments.get(patient_id, []))
