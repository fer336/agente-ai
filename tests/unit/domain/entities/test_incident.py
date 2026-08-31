from datetime import UTC, datetime

from app.domain.entities.incident import INCIDENT_OPEN, INCIDENT_RECOVERED, Incident


def _incident(**overrides: object) -> Incident:
    defaults: dict[str, object] = {
        "id": "inc-1",
        "fingerprint": "dentalink:timeout:search_availability",
        "source": "dentalink",
        "error_type": "dentalink_timeout",
        "operation": "search_availability",
        "severity": "ERROR",
        "occurrences": 1,
        "affected_conversations": 1,
        "first_seen": datetime(2026, 8, 31, 0, 31, tzinfo=UTC),
        "last_seen": datetime(2026, 8, 31, 0, 31, tzinfo=UTC),
        "status": INCIDENT_OPEN,
        "linear_issue_id": None,
        "last_notification_at": None,
        "resolved_at": None,
    }
    defaults.update(overrides)
    return Incident(**defaults)  # type: ignore[arg-type]


def test_creates_incident_with_all_fields():
    incident = _incident()

    assert incident.fingerprint == "dentalink:timeout:search_availability"
    assert incident.status == INCIDENT_OPEN
    assert incident.occurrences == 1


def test_incidents_with_different_status_are_not_equal():
    open_incident = _incident(status=INCIDENT_OPEN)
    recovered_incident = _incident(status=INCIDENT_RECOVERED, resolved_at=datetime.now(UTC))

    assert open_incident != recovered_incident


def test_operation_may_be_none_for_a_two_part_fingerprint():
    incident = _incident(operation=None, fingerprint="dentalink:timeout")

    assert incident.operation is None
    assert incident.fingerprint == "dentalink:timeout"
