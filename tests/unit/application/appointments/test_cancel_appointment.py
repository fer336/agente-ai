import pytest

from app.application.appointments.cancel_appointment import CancelAppointmentUseCase
from app.domain.exceptions.errors import AppointmentNotFoundError
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


@pytest.mark.asyncio
async def test_execute_cancels_the_appointment_via_the_gateway():
    gateway = make_dentalink_gateway(available_slots=[make_slot()])
    created = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=make_slot(), idempotency_key="key-1"
    )
    use_case = CancelAppointmentUseCase(gateway)

    await use_case.execute(str(created.id), idempotency_key="cancel-key-1")

    cancelled = gateway.get_appointment(str(created.id))
    assert cancelled is not None
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_execute_raises_when_the_appointment_does_not_exist():
    gateway = make_dentalink_gateway()
    use_case = CancelAppointmentUseCase(gateway)

    with pytest.raises(AppointmentNotFoundError):
        await use_case.execute("missing", idempotency_key="cancel-key-1")
