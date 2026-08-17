import pytest

from app.domain.repositories.gateways import PatientGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from tests.fixtures.gateways import make_patient_gateway
from tests.fixtures.seed_objects import make_patient


@pytest.mark.asyncio
async def test_find_patient_matches_full_name_and_dni():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni="30111222")
    gateway = make_patient_gateway(patients=[patient])

    found = await gateway.find_patient("Juan Pérez", "30111222")

    assert found == patient


@pytest.mark.asyncio
async def test_find_patient_matches_case_insensitively_and_ignores_whitespace():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni="30111222")
    gateway = make_patient_gateway(patients=[patient])

    found = await gateway.find_patient("  juan pérez  ", " 30111222 ")

    assert found == patient


@pytest.mark.asyncio
async def test_find_patient_returns_none_when_dni_does_not_match():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni="30111222")
    gateway = make_patient_gateway(patients=[patient])

    assert await gateway.find_patient("Juan Pérez", "99999999") is None


@pytest.mark.asyncio
async def test_find_patient_returns_none_when_name_does_not_match():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni="30111222")
    gateway = make_patient_gateway(patients=[patient])

    assert await gateway.find_patient("Otro Nombre", "30111222") is None


@pytest.mark.asyncio
async def test_find_patient_returns_none_when_patient_has_no_dni_on_record():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni=None)
    gateway = make_patient_gateway(patients=[patient])

    assert await gateway.find_patient("Juan Pérez", "30111222") is None


def test_fake_patient_gateway_satisfies_patient_gateway_protocol():
    assert isinstance(FakePatientGateway(), PatientGateway)
