from datetime import datetime

import pytest

from app.domain.exceptions.errors import AppointmentNotFoundError
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


@pytest.mark.asyncio
async def test_search_availability_filters_by_specialty_and_date_range():
    matching = make_slot(id_="slot-1", specialty_id="cleaning")
    other_specialty = make_slot(id_="slot-2", specialty_id="whitening")
    gateway = make_dentalink_gateway(available_slots=[matching, other_specialty])

    results = await gateway.search_availability(
        specialty_id="cleaning",
        professional_id=None,
        date_range=DateTimeRange(datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 2, 0, 0)),
    )

    assert results == [matching]


@pytest.mark.asyncio
async def test_search_availability_returns_empty_list_when_no_slot_matches_professional():
    slot = make_slot(professional_id="prof-1")
    gateway = make_dentalink_gateway(available_slots=[slot])

    results = await gateway.search_availability(
        specialty_id=None,
        professional_id="prof-999",
        date_range=DateTimeRange(datetime(2026, 8, 1, 0, 0), datetime(2026, 8, 2, 0, 0)),
    )

    assert results == []


@pytest.mark.asyncio
async def test_create_appointment_returns_confirmed_appointment_for_the_given_slot():
    slot = make_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])

    appointment = await gateway.create_appointment(make_patient(), slot, idempotency_key="key-1")

    assert appointment.patient_id == "pat-1"
    assert appointment.slot == slot
    assert appointment.status == "confirmed"


@pytest.mark.asyncio
async def test_create_appointment_is_idempotent_for_the_same_key():
    slot = make_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])

    first = await gateway.create_appointment(make_patient(), slot, idempotency_key="key-1")
    second = await gateway.create_appointment(make_patient(), slot, idempotency_key="key-1")

    assert first.id == second.id


@pytest.mark.asyncio
async def test_reschedule_appointment_updates_the_slot_and_keeps_status_confirmed():
    slot = make_slot(id_="slot-1")
    new_slot = make_slot(
        id_="slot-2", start=datetime(2026, 8, 2, 10, 0), end=datetime(2026, 8, 2, 10, 30)
    )
    gateway = make_dentalink_gateway(available_slots=[slot, new_slot])
    original = await gateway.create_appointment(make_patient(), slot, idempotency_key="key-1")

    rescheduled = await gateway.reschedule_appointment(
        str(original.id), new_slot, idempotency_key="key-2"
    )

    assert rescheduled.slot == new_slot
    assert rescheduled.id == original.id
    assert rescheduled.status == "confirmed"


@pytest.mark.asyncio
async def test_reschedule_appointment_raises_when_appointment_id_is_unknown():
    gateway = make_dentalink_gateway()

    with pytest.raises(AppointmentNotFoundError, match="not found") as exc_info:
        await gateway.reschedule_appointment("missing-id", make_slot(), idempotency_key="key-1")

    assert exc_info.value.appointment_id == "missing-id"


@pytest.mark.asyncio
async def test_cancel_appointment_marks_the_appointment_status_cancelled():
    slot = make_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    created = await gateway.create_appointment(make_patient(), slot, idempotency_key="key-1")

    await gateway.cancel_appointment(str(created.id), idempotency_key="key-1-cancel")

    cancelled = gateway.get_appointment(str(created.id))
    assert cancelled is not None
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_appointment_raises_when_appointment_id_is_unknown():
    gateway = make_dentalink_gateway()

    with pytest.raises(AppointmentNotFoundError, match="not found") as exc_info:
        await gateway.cancel_appointment("missing-id", idempotency_key="key-1")

    assert exc_info.value.appointment_id == "missing-id"


def test_fake_dentalink_gateway_satisfies_appointment_gateway_protocol():
    assert isinstance(FakeDentalinkGateway(), AppointmentGateway)
