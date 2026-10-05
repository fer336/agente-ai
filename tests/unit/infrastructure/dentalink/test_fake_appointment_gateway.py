from datetime import UTC, date, datetime

import pytest

from app.domain.repositories.gateways import ReminderAppointment, ReminderAppointmentGateway
from app.infrastructure.dentalink.fake_appointment_gateway import FakeReminderAppointmentGateway


@pytest.mark.asyncio
async def test_fake_reminder_appointment_gateway_keeps_an_inclusive_date_window():
    gateway = FakeReminderAppointmentGateway(
        appointments=[
            ReminderAppointment(
                id="1",
                patient_id="patient-1",
                starts_at=datetime(2026, 10, 10, 9, 30, tzinfo=UTC),
                raw_status_id="2",
                raw_status_name="Atendida",
                state="attended",
            ),
            ReminderAppointment(
                id="2",
                patient_id="patient-2",
                starts_at=datetime(2026, 10, 12, 9, 30, tzinfo=UTC),
                raw_status_id="1",
                raw_status_name="Confirmada",
                state="confirmed",
            ),
        ]
    )

    appointments = await gateway.list_reminder_appointments_for_date_window(
        date(2026, 10, 10), date(2026, 10, 11)
    )

    assert isinstance(gateway, ReminderAppointmentGateway)
    assert [appointment.id for appointment in appointments] == ["1"]


@pytest.mark.asyncio
async def test_fake_reminder_appointment_gateway_records_patient_whatsapp_confirmation_calls():
    gateway = FakeReminderAppointmentGateway()

    await gateway.mark_appointment_confirmed_via_patient_whatsapp("appointment-1")

    assert isinstance(gateway, ReminderAppointmentGateway)
    assert gateway.patient_whatsapp_confirmation_calls == ["appointment-1"]


@pytest.mark.asyncio
async def test_fake_reminder_appointment_gateway_reads_current_appointment_by_id():
    current = ReminderAppointment(
        id="1",
        patient_id="patient-1",
        starts_at=datetime(2026, 10, 10, 9, 30, tzinfo=UTC),
        raw_status_id="2",
        raw_status_name="Atendida",
        state="attended",
    )
    gateway = FakeReminderAppointmentGateway([current])

    assert await gateway.get_reminder_appointment("1") == current
    assert await gateway.get_reminder_appointment("missing") is None
