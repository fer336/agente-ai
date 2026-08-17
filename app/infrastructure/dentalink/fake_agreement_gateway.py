from app.domain.entities.agreement import Agreement


class FakeAgreementGateway:
    """In-memory fake implementing `AgreementGateway` for local dev and tests."""

    def __init__(
        self,
        agreements: list[Agreement] | None = None,
        patient_agreements: dict[str, list[Agreement]] | None = None,
    ) -> None:
        self._agreements = list(agreements) if agreements else []
        self._patient_agreements = dict(patient_agreements) if patient_agreements else {}

    async def list_agreements(self) -> list[Agreement]:
        return list(self._agreements)

    async def find_agreement_by_name(self, name: str) -> Agreement | None:
        normalized = name.strip().casefold()
        for agreement in self._agreements:
            if agreement.name.strip().casefold() == normalized:
                return agreement
        return None

    async def get_patient_agreements(self, patient_id: str) -> list[Agreement]:
        return list(self._patient_agreements.get(patient_id, []))
