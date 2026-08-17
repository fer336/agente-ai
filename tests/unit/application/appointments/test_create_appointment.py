import pytest

from app.application.appointments.create_appointment import CreateAppointmentUseCase
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


@pytest.mark.asyncio
async def test_execute_delegates_to_the_gateway_and_returns_the_appointment():
    slot = make_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    patient = make_patient()
    use_case = CreateAppointmentUseCase(gateway)

    appointment = await use_case.execute(patient, slot, idempotency_key="key-1")

    assert appointment.patient_id == patient.id
    assert appointment.slot == slot
    assert appointment.status == "confirmed"


@pytest.mark.asyncio
async def test_execute_is_idempotent_for_the_same_key():
    slot = make_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    patient = make_patient()
    use_case = CreateAppointmentUseCase(gateway)

    first = await use_case.execute(patient, slot, idempotency_key="key-1")
    second = await use_case.execute(patient, slot, idempotency_key="key-1")

    assert first.id == second.id
