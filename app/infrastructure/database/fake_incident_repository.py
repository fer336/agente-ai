from app.domain.entities.incident import INCIDENT_OPEN, Incident


class FakeIncidentRepository:
    """In-memory fake implementing `IncidentRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, Incident] = {}

    async def get_by_fingerprint(self, fingerprint: str) -> Incident | None:
        for incident in self._by_id.values():
            if incident.fingerprint == fingerprint and incident.status == INCIDENT_OPEN:
                return incident
        return None

    async def save(self, incident: Incident) -> None:
        self._by_id[incident.id] = incident

    async def update(self, incident: Incident) -> None:
        self._by_id[incident.id] = incident

    async def list_open(self) -> list[Incident]:
        return [
            incident for incident in self._by_id.values() if incident.status == INCIDENT_OPEN
        ]
