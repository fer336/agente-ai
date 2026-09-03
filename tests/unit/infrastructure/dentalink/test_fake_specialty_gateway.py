import pytest

from app.domain.repositories.gateways import SpecialtyGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway
from tests.fixtures.gateways import make_specialty_gateway
from tests.fixtures.seed_objects import make_specialty


@pytest.mark.asyncio
async def test_list_specialties_returns_all_configured_specialties():
    ortodoncia = make_specialty(id_="spec-1", name="Ortodoncia")
    endodoncia = make_specialty(id_="spec-2", name="Endodoncia")
    gateway = make_specialty_gateway(specialties=[ortodoncia, endodoncia])

    results = await gateway.list_specialties()

    assert results == [ortodoncia, endodoncia]


@pytest.mark.asyncio
async def test_list_specialties_returns_empty_list_by_default():
    gateway = make_specialty_gateway()

    assert await gateway.list_specialties() == []


def test_fake_specialty_gateway_satisfies_specialty_gateway_protocol():
    assert isinstance(FakeSpecialtyGateway(), SpecialtyGateway)
