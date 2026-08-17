import pytest

from app.application.patients.identify_patient import IdentifyPatientUseCase
from tests.fixtures.gateways import make_patient_gateway
from tests.fixtures.seed_objects import make_patient


@pytest.mark.asyncio
async def test_execute_returns_the_matching_patient():
    patient = make_patient(id_="pat-1", full_name="Juan Pérez", dni="30111222")
    use_case = IdentifyPatientUseCase(make_patient_gateway(patients=[patient]))

    result = await use_case.execute("Juan Pérez", "30111222")

    assert result == patient


@pytest.mark.asyncio
async def test_execute_returns_none_when_no_patient_matches():
    use_case = IdentifyPatientUseCase(make_patient_gateway())

    result = await use_case.execute("Nadie", "00000000")

    assert result is None
