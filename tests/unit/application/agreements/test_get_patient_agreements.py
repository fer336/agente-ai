import pytest

from app.application.agreements.get_patient_agreements import GetPatientAgreementsUseCase
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_execute_returns_the_patients_registered_agreements():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(patient_agreements={"pat-1": [osde]})
    use_case = GetPatientAgreementsUseCase(gateway)

    result = await use_case.execute("pat-1")

    assert result == [osde]


@pytest.mark.asyncio
async def test_execute_returns_empty_list_for_unknown_patient():
    gateway = make_agreement_gateway()
    use_case = GetPatientAgreementsUseCase(gateway)

    result = await use_case.execute("unknown")

    assert result == []
