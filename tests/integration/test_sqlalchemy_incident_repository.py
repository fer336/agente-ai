from datetime import UTC, datetime, timedelta

from app.domain.entities.incident import INCIDENT_OPEN, INCIDENT_RECOVERED, Incident
from app.infrastructure.database.repositories.incident_repository import (
    SqlAlchemyIncidentRepository,
)


def _incident(
    incident_id: str,
    fingerprint: str = "dentalink:dentalink_timeout:search_availability",
    status: str = INCIDENT_OPEN,
    occurrences: int = 1,
    first_seen=None,
    last_seen=None,
) -> Incident:
    now = first_seen if first_seen is not None else datetime(2026, 8, 31, 0, 31, tzinfo=UTC)
    return Incident(
        id=incident_id,
        fingerprint=fingerprint,
        source="dentalink",
        error_type="dentalink_timeout",
        operation="search_availability",
        severity="ERROR",
        occurrences=occurrences,
        affected_conversations=1,
        first_seen=now,
        last_seen=last_seen if last_seen is not None else now,
        status=status,
        linear_issue_id=None,
        last_notification_at=None,
        resolved_at=None,
    )


async def test_save_then_get_by_fingerprint_round_trips(db_session):
    repository = SqlAlchemyIncidentRepository(db_session)
    incident = _incident("inc-1")

    await repository.save(incident)
    fetched = await repository.get_by_fingerprint(incident.fingerprint)

    assert fetched is not None
    assert fetched.id == "inc-1"
    assert fetched.occurrences == 1


async def test_get_by_fingerprint_returns_none_when_missing(db_session):
    repository = SqlAlchemyIncidentRepository(db_session)

    assert await repository.get_by_fingerprint("missing:fingerprint") is None


async def test_get_by_fingerprint_ignores_a_recovered_incident(db_session):
    repository = SqlAlchemyIncidentRepository(db_session)
    await repository.save(_incident("inc-1", status=INCIDENT_RECOVERED))

    fingerprint = "dentalink:dentalink_timeout:search_availability"
    assert await repository.get_by_fingerprint(fingerprint) is None


async def test_update_persists_changes(db_session):
    repository = SqlAlchemyIncidentRepository(db_session)
    incident = _incident("inc-1", occurrences=1)
    await repository.save(incident)

    incident.occurrences = 2
    incident.last_seen = incident.first_seen + timedelta(minutes=5)
    await repository.update(incident)

    fetched = await repository.get_by_fingerprint(incident.fingerprint)
    assert fetched is not None
    assert fetched.occurrences == 2


async def test_list_open_only_returns_open_incidents(db_session):
    repository = SqlAlchemyIncidentRepository(db_session)
    await repository.save(_incident("inc-open", status=INCIDENT_OPEN))
    await repository.save(
        _incident("inc-recovered", fingerprint="other:fp", status=INCIDENT_RECOVERED)
    )

    open_incidents = await repository.list_open()

    assert [i.id for i in open_incidents] == ["inc-open"]
