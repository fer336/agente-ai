import pytest

from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from tests.fixtures.gateways import make_specialty_gateway
from tests.fixtures.seed_objects import make_specialty


@pytest.mark.asyncio
async def test_execute_returns_all_specialties_from_the_gateway():
    ortodoncia = make_specialty(id_="spec-1", name="Ortodoncia")
    gateway = make_specialty_gateway(specialties=[ortodoncia])
    use_case = ListSpecialtiesUseCase(gateway)

    result = await use_case.execute()

    assert result == [ortodoncia]
