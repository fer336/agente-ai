from app.domain.entities.patient import Patient


class FakePatientGateway:
    """In-memory fake implementing `PatientGateway` for local dev and tests."""

    def __init__(self, patients: list[Patient] | None = None) -> None:
        self._patients = list(patients) if patients else []

    async def find_patient(self, full_name: str, dni: str) -> Patient | None:
        normalized_name = full_name.strip().casefold()
        normalized_dni = dni.strip()
        for patient in self._patients:
            if (
                patient.full_name.strip().casefold() == normalized_name
                and patient.dni is not None
                and patient.dni.strip() == normalized_dni
            ):
                return patient
        return None
