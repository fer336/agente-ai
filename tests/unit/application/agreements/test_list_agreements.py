import pytest

from app.application.agreements.list_agreements import ListAgreementsUseCase
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_execute_returns_all_agreements_from_the_gateway():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(agreements=[osde])
    use_case = ListAgreementsUseCase(gateway)

    result = await use_case.execute()

    assert result == [osde]
