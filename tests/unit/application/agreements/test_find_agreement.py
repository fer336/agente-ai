import pytest

from app.application.agreements.find_agreement import FindAgreementByNameUseCase
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_execute_returns_the_matching_agreement():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(agreements=[osde])
    use_case = FindAgreementByNameUseCase(gateway)

    result = await use_case.execute("OSDE")

    assert result == osde


@pytest.mark.asyncio
async def test_execute_returns_none_when_no_agreement_matches():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])
    use_case = FindAgreementByNameUseCase(gateway)

    result = await use_case.execute("Swiss Medical")

    assert result is None
