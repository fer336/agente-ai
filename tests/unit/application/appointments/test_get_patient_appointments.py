import pytest

from app.application.appointments.get_patient_appointments import GetPatientAppointmentsUseCase
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


@pytest.mark.asyncio
async def test_execute_returns_the_patients_appointments():
    gateway = make_dentalink_gateway()
    await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=make_slot(id_="slot-1"), idempotency_key="key-1"
    )
    use_case = GetPatientAppointmentsUseCase(gateway)

    appointments = await use_case.execute("pat-1")

    assert len(appointments) == 1
    assert appointments[0].patient_id == "pat-1"


@pytest.mark.asyncio
async def test_execute_filters_out_cancelled_appointments():
    gateway = make_dentalink_gateway()
    patient = make_patient(id_="pat-1")
    created = await gateway.create_appointment(
        patient=patient, slot=make_slot(id_="slot-1"), idempotency_key="key-1"
    )
    await gateway.cancel_appointment(str(created.id), idempotency_key="cancel-key-1")
    use_case = GetPatientAppointmentsUseCase(gateway)

    appointments = await use_case.execute("pat-1")

    assert appointments == []


@pytest.mark.asyncio
async def test_execute_returns_empty_list_when_patient_has_no_appointments():
    gateway = make_dentalink_gateway()
    use_case = GetPatientAppointmentsUseCase(gateway)

    appointments = await use_case.execute("pat-missing")

    assert appointments == []
