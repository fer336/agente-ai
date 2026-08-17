import pytest

from app.domain.repositories.gateways import AgreementGateway
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from tests.fixtures.gateways import make_agreement_gateway
from tests.fixtures.seed_objects import make_agreement


@pytest.mark.asyncio
async def test_list_agreements_returns_all_configured_agreements():
    osde = make_agreement(id_="agr-1", name="OSDE")
    swiss = make_agreement(id_="agr-2", name="Swiss Medical")
    gateway = make_agreement_gateway(agreements=[osde, swiss])

    results = await gateway.list_agreements()

    assert results == [osde, swiss]


@pytest.mark.asyncio
async def test_find_agreement_by_name_matches_case_insensitively():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(agreements=[osde])

    found = await gateway.find_agreement_by_name("osde")

    assert found == osde


@pytest.mark.asyncio
async def test_find_agreement_by_name_ignores_surrounding_whitespace():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(agreements=[osde])

    found = await gateway.find_agreement_by_name("  OSDE  ")

    assert found == osde


@pytest.mark.asyncio
async def test_find_agreement_by_name_returns_none_when_no_match():
    gateway = make_agreement_gateway(agreements=[make_agreement(name="OSDE")])

    assert await gateway.find_agreement_by_name("Swiss Medical") is None


@pytest.mark.asyncio
async def test_get_patient_agreements_returns_configured_agreements_for_that_patient():
    osde = make_agreement(id_="agr-1", name="OSDE")
    gateway = make_agreement_gateway(patient_agreements={"pat-1": [osde]})

    results = await gateway.get_patient_agreements("pat-1")

    assert results == [osde]


@pytest.mark.asyncio
async def test_get_patient_agreements_returns_empty_list_for_unknown_patient():
    gateway = make_agreement_gateway()

    assert await gateway.get_patient_agreements("unknown") == []


def test_fake_agreement_gateway_satisfies_agreement_gateway_protocol():
    assert isinstance(FakeAgreementGateway(), AgreementGateway)
