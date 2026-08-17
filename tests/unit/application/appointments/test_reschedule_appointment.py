from datetime import datetime

import pytest

from app.application.appointments.reschedule_appointment import RescheduleAppointmentUseCase
from app.domain.exceptions.errors import AppointmentNotFoundError
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


@pytest.mark.asyncio
async def test_execute_delegates_to_the_gateway_and_returns_the_rescheduled_appointment():
    gateway = make_dentalink_gateway()
    created = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=make_slot(id_="slot-1"), idempotency_key="key-1"
    )
    new_slot = make_slot(
        id_="slot-2", start=datetime(2026, 8, 2, 10, 0), end=datetime(2026, 8, 2, 10, 30)
    )
    use_case = RescheduleAppointmentUseCase(gateway)

    rescheduled = await use_case.execute(
        str(created.id), new_slot, idempotency_key="reschedule-key-1"
    )

    assert rescheduled.id == created.id
    assert rescheduled.slot == new_slot


@pytest.mark.asyncio
async def test_execute_raises_when_the_appointment_does_not_exist():
    gateway = make_dentalink_gateway()
    use_case = RescheduleAppointmentUseCase(gateway)

    with pytest.raises(AppointmentNotFoundError):
        await use_case.execute("missing", make_slot(), idempotency_key="reschedule-key-1")
