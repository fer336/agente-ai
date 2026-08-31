from typing import Protocol, runtime_checkable

from app.domain.entities.incident import Incident


@runtime_checkable
class IncidentRepository(Protocol):
    """Port to durable storage for deduplicated incidents (PRD.md §49)."""

    async def get_by_fingerprint(self, fingerprint: str) -> Incident | None: ...

    async def save(self, incident: Incident) -> None: ...

    async def update(self, incident: Incident) -> None: ...

    async def list_open(self) -> list[Incident]:
        """Lists every `INCIDENT_OPEN` incident — the recovery sweep's
        input (`app.workers.incident_tasks.check_incident_recovery`,
        PRD.md §51).
        """
        ...
