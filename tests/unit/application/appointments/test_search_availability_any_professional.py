from datetime import UTC, datetime, timedelta

import pytest

from app.application.appointments.search_availability_any_professional import (
    SearchAvailabilityAnyProfessionalUseCase,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.professional import Professional
from app.domain.value_objects.date_time_range import DateTimeRange


class _RecordingGateway:
    """Spy `AppointmentGateway` recording every `search_specialty_availability`
    call; it returns the slots it was built with (already "the specialty's")
    exactly as the real gateway's server-side `id_especialidad` filter would,
    sorted and cut at `limit`."""

    def __init__(
        self, slots: list[AppointmentSlot], professionals: list[Professional]
    ) -> None:
        self._slots = slots
        self._professionals = professionals
        self.calls: list[tuple[str, DateTimeRange, int]] = []

    async def search_specialty_availability(
        self, specialty_id: str, date_range: DateTimeRange, limit: int
    ) -> list[AppointmentSlot]:
        self.calls.append((specialty_id, date_range, limit))
        matches = [slot for slot in self._slots if date_range.contains(slot.time_range.start)]
        matches.sort(key=lambda slot: slot.time_range.start)
        return matches[:limit]

    async def list_professionals(self, specialty_id: str | None = None) -> list[Professional]:
        return [
            professional
            for professional in self._professionals
            if specialty_id is None or professional.specialty_id == specialty_id
        ]


def _professional(i: int, specialty_id: str = "ortho") -> Professional:
    return Professional(id=f"prof-{i}", full_name=f"Prof {i}", specialty_id=specialty_id)


def _slot(id_: str, professional_id: str, start: datetime) -> AppointmentSlot:
    return AppointmentSlot(
        id=id_,
        professional_id=professional_id,
        specialty_id="",
        time_range=DateTimeRange(start, start + timedelta(minutes=30)),
    )


def _sixty_day_range(now: datetime) -> DateTimeRange:
    return DateTimeRange(now, now + timedelta(days=60))


@pytest.mark.asyncio
async def test_execute_searches_by_specialty_with_one_gateway_call():
    now = datetime(2026, 9, 22, 19, 58, tzinfo=UTC)
    window = _sixty_day_range(now)
    gateway = _RecordingGateway(slots=[], professionals=[_professional(1)])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    await use_case.execute(specialty_id="ortho", date_range=window, target_slot_count=27)

    # The specialty filter and the day walk live in the gateway: the use
    # case no longer issues one query per calendar day.
    assert gateway.calls == [("ortho", window, 27)]


@pytest.mark.asyncio
async def test_execute_skips_the_search_when_the_specialty_has_no_professionals():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    gateway = _RecordingGateway(slots=[], professionals=[_professional(1, "other")])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, names = await use_case.execute(
        specialty_id="ortho", date_range=_sixty_day_range(now), target_slot_count=27
    )

    assert result == []
    assert names == {}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_execute_returns_names_and_slots_far_beyond_the_first_week():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    slots = [_slot("far", professional.id, now + timedelta(days=12))]
    gateway = _RecordingGateway(slots=slots, professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, names = await use_case.execute(
        specialty_id="ortho", date_range=_sixty_day_range(now), target_slot_count=27
    )

    assert [slot.id for slot in result] == ["far"]
    assert names == {professional.id: professional.full_name}


@pytest.mark.asyncio
async def test_execute_drops_slots_of_professionals_outside_the_specialty():
    # Safety net kept on purpose: `list_professionals` only returns ENABLED
    # professionals of the specialty, so a slot of anyone else (e.g. a
    # disabled one the agenda still lists) is never offered.
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    mine = _slot("mine", professional.id, now + timedelta(hours=1))
    foreign = _slot("foreign", "prof-99", now + timedelta(hours=2))
    gateway = _RecordingGateway(slots=[mine, foreign], professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, _ = await use_case.execute(
        specialty_id="ortho", date_range=_sixty_day_range(now), target_slot_count=27
    )

    assert [slot.id for slot in result] == ["mine"]


@pytest.mark.asyncio
async def test_execute_dedupes_slots_that_share_an_id_keeping_the_first():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    earlier = _slot("dup-id", professional.id, now + timedelta(hours=1))
    later_same_id = _slot("dup-id", professional.id, now + timedelta(hours=2))
    gateway = _RecordingGateway(slots=[earlier, later_same_id], professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, _ = await use_case.execute(
        specialty_id="ortho", date_range=_sixty_day_range(now), target_slot_count=27
    )

    assert [slot.id for slot in result] == ["dup-id"]
    assert result[0].time_range.start == earlier.time_range.start


@pytest.mark.asyncio
async def test_execute_returns_at_most_the_target_sorted_by_start():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    slots = [_slot(f"slot-{i}", professional.id, now + timedelta(hours=3 - i)) for i in range(3)]
    gateway = _RecordingGateway(slots=slots, professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, _ = await use_case.execute(
        specialty_id="ortho", date_range=_sixty_day_range(now), target_slot_count=2
    )

    assert [slot.id for slot in result] == ["slot-2", "slot-1"]
