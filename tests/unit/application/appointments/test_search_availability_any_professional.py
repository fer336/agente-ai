from datetime import UTC, datetime, time, timedelta

import pytest

from app.application.appointments.search_availability_any_professional import (
    SearchAvailabilityAnyProfessionalUseCase,
)
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.professional import Professional
from app.domain.value_objects.date_time_range import DateTimeRange


class _RecordingGateway:
    """Spy `AppointmentGateway` that records every `search_availability`
    call's `date_range`.

    The real `DentalinkAppointmentGateway` issues one `/v5/agendas` HTTP
    call PER CALENDAR DATE within whatever `date_range` it receives (see
    its own `search_availability` docstring/loop). So a `date_range` that
    spans two calendar dates costs two real HTTP requests even though the
    use case only made one port call — recording the `date_range` each
    call carried lets these tests assert the use case never hands the
    gateway a window spanning more than one calendar date, which is what
    keeps the real request count at one per iteration.
    """

    def __init__(
        self, slots: list[AppointmentSlot], professionals: list[Professional]
    ) -> None:
        self._slots = slots
        self._professionals = professionals
        self.calls: list[DateTimeRange] = []

    async def search_availability(
        self,
        specialty_id: str | None,
        professional_id: str | None,
        date_range: DateTimeRange,
        limit: int | None = None,
    ) -> list[AppointmentSlot]:
        self.calls.append(date_range)
        matches = [slot for slot in self._slots if date_range.contains(slot.time_range.start)]
        return matches if limit is None else matches[:limit]

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


def _seven_calendar_day_range(now: datetime) -> DateTimeRange:
    today_midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    return DateTimeRange(now, today_midnight + timedelta(days=7))


@pytest.mark.asyncio
async def test_execute_never_asks_for_a_window_spanning_more_than_one_calendar_date():
    now = datetime(2026, 9, 22, 19, 58, tzinfo=UTC)  # deliberately not midnight
    gateway = _RecordingGateway(slots=[], professionals=[_professional(1)])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    await use_case.execute(
        specialty_id="ortho", date_range=_seven_calendar_day_range(now), target_slot_count=18
    )

    assert gateway.calls
    for call_range in gateway.calls:
        last_included_moment = call_range.end - timedelta(microseconds=1)
        assert call_range.start.date() == last_included_moment.date()


@pytest.mark.asyncio
async def test_execute_makes_at_most_one_request_per_calendar_day_in_a_seven_day_window():
    now = datetime(2026, 9, 22, 19, 58, tzinfo=UTC)
    gateway = _RecordingGateway(slots=[], professionals=[_professional(1)])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    await use_case.execute(
        specialty_id="ortho", date_range=_seven_calendar_day_range(now), target_slot_count=18
    )

    assert len(gateway.calls) <= 7


@pytest.mark.asyncio
async def test_execute_stops_walking_once_the_target_slot_count_is_reached():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    slots = [_slot(f"slot-{i}", professional.id, now + timedelta(hours=i)) for i in range(3)]
    gateway = _RecordingGateway(slots=slots, professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, _ = await use_case.execute(
        specialty_id="ortho", date_range=_seven_calendar_day_range(now), target_slot_count=2
    )

    assert len(result) == 2
    # All 3 slots fall on `now`'s own calendar day, so the target is
    # already reached after the first request.
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_execute_dedupes_slots_that_share_an_id_keeping_the_first():
    now = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    professional = _professional(1)
    earlier = _slot("dup-id", professional.id, now + timedelta(hours=1))
    later_same_id = _slot("dup-id", professional.id, now + timedelta(hours=2))
    gateway = _RecordingGateway(slots=[earlier, later_same_id], professionals=[professional])
    use_case = SearchAvailabilityAnyProfessionalUseCase(gateway)

    result, _ = await use_case.execute(
        specialty_id="ortho", date_range=_seven_calendar_day_range(now), target_slot_count=18
    )

    assert [slot.id for slot in result] == ["dup-id"]
    assert result[0].time_range.start == earlier.time_range.start
