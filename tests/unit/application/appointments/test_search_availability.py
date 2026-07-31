from datetime import datetime

import pytest

from app.application.appointments.search_availability import SearchAvailabilityUseCase
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


def _slot(
    id_="slot-1",
    professional_id="prof-1",
    specialty_id="cleaning",
    start=datetime(2026, 8, 1, 10, 0),
    end=datetime(2026, 8, 1, 10, 30),
):
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id=specialty_id,
        time_range=DateTimeRange(start, end),
    )


@pytest.mark.asyncio
async def test_execute_returns_slots_the_gateway_finds_for_the_given_filters():
    matching = _slot(id_="slot-1", specialty_id="cleaning")
    other_specialty = _slot(id_="slot-2", specialty_id="whitening")
    gateway = FakeDentalinkGateway(available_slots=[matching, other_specialty])
    use_case = SearchAvailabilityUseCase(gateway)

    result = await use_case.execute(
        specialty_id="cleaning",
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 2, 0, 0)),
    )

    assert result == [matching]


@pytest.mark.asyncio
async def test_execute_returns_empty_list_when_gateway_has_no_match():
    slot = _slot(specialty_id="cleaning")
    gateway = FakeDentalinkGateway(available_slots=[slot])
    use_case = SearchAvailabilityUseCase(gateway)

    result = await use_case.execute(
        specialty_id="whitening",
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 2, 0, 0)),
    )

    assert result == []
