from app.domain.entities.patient import Patient
from app.domain.exceptions.errors import PatientAlreadyExistsError
from app.domain.value_objects.dni import Dni
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.schemas import full_names_match


class FakePatientGateway:
    """In-memory fake implementing `PatientGateway` for local dev and tests."""

    def __init__(self, patients: list[Patient] | None = None) -> None:
        self._patients = list(patients) if patients else []

    async def find_patient(self, full_name: str, dni: str) -> Patient | None:
        normalized_dni = dni.strip()
        for patient in self._patients:
            if (
                full_names_match(patient.full_name, full_name)
                and patient.dni is not None
                and patient.dni.strip() == normalized_dni
            ):
                return patient
        return None

<<<<<<< Updated upstream
    async def create_patient(
        self, full_name: str, dni: str, phone: PhoneNumber, email: str | None = None
    ) -> Patient:
=======
    async def get_patient_by_id(self, patient_id: str) -> Patient | None:
        for patient in self._patients:
            if patient.id == patient_id:
                return patient
        return None

    async def create_patient(self, full_name: str, dni: str, phone: PhoneNumber) -> Patient:
>>>>>>> Stashed changes
        validated_dni = Dni(dni)
        existing = self._find_by_rut(validated_dni)
        if existing is not None:
            raise PatientAlreadyExistsError(validated_dni.value, existing.id)

        patient = Patient(
            id=str(len(self._patients) + 1),
            full_name=full_name.strip(),
            phone=phone,
            dni=validated_dni.value,
            email=email,
        )
        self._patients.append(patient)
        return patient

    def _find_by_rut(self, dni: Dni) -> Patient | None:
        for patient in self._patients:
            if patient.dni is None:
                continue
            try:
                existing_dni = Dni(patient.dni)
            except ValueError:
                # Pre-existing records may carry a differently-shaped
                # identifier (e.g. a seed value outside the 7-8 digit
                # range) — those can never collide with a validated DNI,
                # so skip rather than raise (mirrors `find_patient`'s own
                # tolerant matching).
                continue
            if existing_dni.value == dni.value:
                return patient
        return None
