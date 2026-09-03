import pytest

from app.domain.exceptions.errors import PatientAlreadyExistsError
from app.domain.repositories.gateways import PatientGateway
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from tests.fixtures.gateways import make_patient_gateway
from tests.fixtures.seed_objects import make_patient

_VALID_DNI = "30111222"
_OTHER_VALID_DNI = "40222333"


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


@pytest.mark.asyncio
async def test_create_patient_stores_and_returns_the_new_patient():
    gateway = make_patient_gateway()

    created = await gateway.create_patient(
        "Maria Soto", _VALID_DNI, PhoneNumber("+56912345678")
    )

    assert created.full_name == "Maria Soto"
    assert created.dni == _VALID_DNI
    assert created.phone == PhoneNumber("+56912345678")
    found = await gateway.find_patient("Maria Soto", _VALID_DNI)
    assert found == created


@pytest.mark.asyncio
async def test_create_patient_rejects_an_invalid_dni_before_storing_anything():
    gateway = make_patient_gateway()

    with pytest.raises(ValueError, match="DNI"):
        await gateway.create_patient("Maria Soto", "not-a-dni", PhoneNumber("+56912345678"))


@pytest.mark.asyncio
async def test_create_patient_raises_a_typed_conflict_for_a_duplicate_dni():
    existing = make_patient(id_="pat-1", full_name="Maria Soto", dni=_VALID_DNI)
    gateway = make_patient_gateway(patients=[existing])

    with pytest.raises(PatientAlreadyExistsError) as exc_info:
        await gateway.create_patient("Maria Soto Otra", _VALID_DNI, PhoneNumber("+56911111111"))

    assert exc_info.value.existing_patient_id == "pat-1"


@pytest.mark.asyncio
async def test_create_patient_tolerates_pre_existing_malformed_dni_records():
    # A legacy seed record whose dni doesn't fit the 7-8 digit DNI shape
    # must never crash the duplicate check when creating a genuinely
    # valid-DNI patient.
    existing = make_patient(id_="pat-1", full_name="Juan Perez", dni="not-a-dni")
    gateway = make_patient_gateway(patients=[existing])

    created = await gateway.create_patient(
        "Maria Soto", _OTHER_VALID_DNI, PhoneNumber("+56912345678")
    )

    assert created.dni == _OTHER_VALID_DNI
