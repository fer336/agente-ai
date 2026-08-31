from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.incident import INCIDENT_OPEN, Incident
from app.infrastructure.database.models.incident import IncidentModel


class SqlAlchemyIncidentRepository:
    """`IncidentRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_fingerprint(self, fingerprint: str) -> Incident | None:
        result = await self._session.execute(
            select(IncidentModel).where(
                IncidentModel.fingerprint == fingerprint,
                IncidentModel.status == INCIDENT_OPEN,
            )
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

    async def save(self, incident: Incident) -> None:
        model = await self._session.get(IncidentModel, incident.id)
        if model is None:
            model = IncidentModel(id=incident.id)
            self._session.add(model)
        _apply(model, incident)
        await self._session.flush()

    async def update(self, incident: Incident) -> None:
        await self.save(incident)

    async def list_open(self) -> list[Incident]:
        result = await self._session.execute(
            select(IncidentModel).where(IncidentModel.status == INCIDENT_OPEN)
        )
        return [_to_entity(model) for model in result.scalars().all()]


def _apply(model: IncidentModel, incident: Incident) -> None:
    model.fingerprint = incident.fingerprint
    model.source = incident.source
    model.error_type = incident.error_type
    model.operation = incident.operation
    model.severity = incident.severity
    model.occurrences = incident.occurrences
    model.affected_conversations = incident.affected_conversations
    model.first_seen = incident.first_seen
    model.last_seen = incident.last_seen
    model.status = incident.status
    model.linear_issue_id = incident.linear_issue_id
    model.last_notification_at = incident.last_notification_at
    model.resolved_at = incident.resolved_at


def _to_entity(model: IncidentModel) -> Incident:
    return Incident(
        id=model.id,
        fingerprint=model.fingerprint,
        source=model.source,
        error_type=model.error_type,
        operation=model.operation,
        severity=model.severity,
        occurrences=model.occurrences,
        affected_conversations=model.affected_conversations,
        first_seen=model.first_seen,
        last_seen=model.last_seen,
        status=model.status,
        linear_issue_id=model.linear_issue_id,
        last_notification_at=model.last_notification_at,
        resolved_at=model.resolved_at,
    )
