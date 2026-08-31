from dataclasses import replace

import pytest

from app.domain.entities.incident import INCIDENT_OPEN, INCIDENT_RECOVERED
from app.domain.repositories.incident_repository import IncidentRepository
from app.infrastructure.database.fake_incident_repository import FakeIncidentRepository
from tests.fixtures.gateways import make_incident_repository
from tests.fixtures.seed_objects import make_incident


def test_fake_incident_repository_satisfies_protocol():
    assert isinstance(FakeIncidentRepository(), IncidentRepository)


@pytest.mark.asyncio
async def test_save_then_get_by_fingerprint_round_trips():
    repository = make_incident_repository()
    incident = make_incident(id_="inc-1", fingerprint="dentalink:timeout:search_availability")

    await repository.save(incident)
    fetched = await repository.get_by_fingerprint("dentalink:timeout:search_availability")

    assert fetched is incident


@pytest.mark.asyncio
async def test_get_by_fingerprint_returns_none_when_missing():
    repository = make_incident_repository()

    assert await repository.get_by_fingerprint("missing:fingerprint") is None


@pytest.mark.asyncio
async def test_get_by_fingerprint_ignores_a_recovered_incident_with_the_same_fingerprint():
    repository = make_incident_repository()
    recovered = make_incident(
        id_="inc-old",
        fingerprint="dentalink:timeout:search_availability",
        status=INCIDENT_RECOVERED,
    )
    await repository.save(recovered)

    assert await repository.get_by_fingerprint("dentalink:timeout:search_availability") is None


@pytest.mark.asyncio
async def test_update_persists_changes():
    repository = make_incident_repository()
    incident = make_incident(id_="inc-1", occurrences=1)
    await repository.save(incident)

    await repository.update(replace(incident, occurrences=2))

    fetched = await repository.get_by_fingerprint(incident.fingerprint)
    assert fetched is not None
    assert fetched.occurrences == 2


@pytest.mark.asyncio
async def test_list_open_only_returns_open_incidents():
    repository = make_incident_repository()
    await repository.save(make_incident(id_="inc-open", status=INCIDENT_OPEN))
    await repository.save(
        make_incident(id_="inc-recovered", fingerprint="other:fp", status=INCIDENT_RECOVERED)
    )

    open_incidents = await repository.list_open()

    assert [i.id for i in open_incidents] == ["inc-open"]
