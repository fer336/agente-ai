import pytest

from app.domain.value_objects.appointment_id import AppointmentId
from app.infrastructure.dentalink.exceptions import DentalinkInvalidResponseError
from app.infrastructure.dentalink.schemas import (
    agreement_from_convenio,
    appointment_from_cita,
    professional_from_dentista,
    resolve_cancellation_state_id,
    slot_from_agenda,
    treatment_from_tratamiento,
)


def test_professional_from_dentista_prefers_id_dentista():
    professional = professional_from_dentista(
        {"id_dentista": 626, "nombre": "Laura", "apellidos": "Pérez", "id_especialidad": 3}
    )

    assert professional.id == "626"
    assert professional.full_name == "Laura Pérez"
    assert professional.specialty_id == "3"


def test_professional_from_dentista_falls_back_to_id_profesional():
    professional = professional_from_dentista(
        {"id_profesional": 900, "nombre": "Dr.", "apellidos": "Roe"}
    )

    assert professional.id == "900"
    assert professional.specialty_id is None


def test_professional_from_dentista_raises_when_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        professional_from_dentista({"nombre": "Dr. Roe"})


def test_slot_from_agenda_maps_id_profesional_fecha_and_hora_inicio():
    slot = slot_from_agenda(
        {
            "id": "slot-1",
            "id_profesional": 626,
            "id_especialidad": "cleaning",
            "fecha": "2026-08-15",
            "hora_inicio": "15:30",
            "duracion": 30,
        },
        default_duration_minutes=30,
    )

    assert slot.id == "slot-1"
    assert slot.professional_id == "626"
    assert slot.specialty_id == "cleaning"
    assert slot.time_range.start.hour == 15
    assert slot.time_range.start.minute == 30
    assert slot.time_range.duration().total_seconds() == 30 * 60


def test_slot_from_agenda_falls_back_to_id_dentista_and_default_duration():
    slot = slot_from_agenda(
        {"id_dentista": 900, "fecha": "2026-08-15", "hora_inicio": "09:00"},
        default_duration_minutes=45,
    )

    assert slot.professional_id == "900"
    assert slot.time_range.duration().total_seconds() == 45 * 60


def test_slot_from_agenda_raises_when_professional_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        slot_from_agenda(
            {"fecha": "2026-08-15", "hora_inicio": "09:00"}, default_duration_minutes=30
        )


def test_slot_from_agenda_raises_when_fecha_or_hora_inicio_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        slot_from_agenda({"id_profesional": 1, "fecha": "2026-08-15"}, default_duration_minutes=30)


def test_appointment_from_cita_maps_confirmed_status_when_id_estado_is_not_cancellation():
    appointment = appointment_from_cita(
        {
            "id": 42,
            "id_paciente": "pat-1",
            "id_dentista": 626,
            "fecha": "2026-08-15",
            "hora_inicio": "15:30",
            "duracion": 30,
            "id_estado": 1,
        },
        cancelled_state_id="9",
    )

    assert appointment.id == AppointmentId("42")
    assert appointment.patient_id == "pat-1"
    assert appointment.status == "confirmed"


def test_appointment_from_cita_maps_cancelled_status_when_id_estado_matches():
    appointment = appointment_from_cita(
        {
            "id": 42,
            "id_paciente": "pat-1",
            "id_dentista": 626,
            "fecha": "2026-08-15",
            "hora_inicio": "15:30",
            "id_estado": 9,
        },
        cancelled_state_id="9",
    )

    assert appointment.status == "cancelled"


def test_appointment_from_cita_defaults_to_confirmed_when_cancelled_state_id_is_unknown():
    appointment = appointment_from_cita(
        {"id": 42, "id_paciente": "pat-1", "fecha": "2026-08-15", "id_estado": 9},
        cancelled_state_id=None,
    )

    assert appointment.status == "confirmed"


def test_appointment_from_cita_raises_when_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        appointment_from_cita({"id_paciente": "pat-1"}, cancelled_state_id=None)


def test_agreement_from_convenio_maps_id_and_nombre():
    agreement = agreement_from_convenio({"id": 7, "nombre": "OSDE"})

    assert agreement.id == "7"
    assert agreement.name == "OSDE"


def test_agreement_from_convenio_falls_back_to_id_convenio():
    agreement = agreement_from_convenio({"id_convenio": 8, "nombre": "Swiss Medical"})

    assert agreement.id == "8"


def test_agreement_from_convenio_raises_when_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        agreement_from_convenio({"nombre": "OSDE"})


def test_resolve_cancellation_state_id_matches_anulada_by_name():
    state_id = resolve_cancellation_state_id(
        [{"id": 1, "nombre": "Confirmada"}, {"id": 9, "nombre": "Anulada"}]
    )

    assert state_id == "9"


def test_resolve_cancellation_state_id_matches_cancelada_case_insensitively():
    state_id = resolve_cancellation_state_id([{"id": 5, "nombre": "CANCELADA"}])

    assert state_id == "5"


def test_resolve_cancellation_state_id_returns_none_when_no_match():
    state_id = resolve_cancellation_state_id([{"id": 1, "nombre": "Confirmada"}])

    assert state_id is None


def test_treatment_from_tratamiento_maps_confirmed_live_shape():
    treatment = treatment_from_tratamiento(
        {
            "id": 7998,
            "id_paciente": 5844,
            "nombre": "Nuevo plan de tratamiento",
            "finalizado": 0,
            "total": 1000,
            "abonado": 400,
            "deuda": 600,
        }
    )

    assert treatment.id == "7998"
    assert treatment.patient_id == "5844"
    assert treatment.name == "Nuevo plan de tratamiento"
    assert treatment.is_finished is False
    assert treatment.total == 1000.0
    assert treatment.paid == 400.0
    assert treatment.debt == 600.0


def test_treatment_from_tratamiento_defaults_missing_money_fields_to_zero():
    treatment = treatment_from_tratamiento({"id": 1, "id_paciente": 2, "nombre": "Plan"})

    assert treatment.total == 0.0
    assert treatment.paid == 0.0
    assert treatment.debt == 0.0


def test_treatment_from_tratamiento_raises_when_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        treatment_from_tratamiento({"id_paciente": 2, "nombre": "Plan"})


def test_treatment_from_tratamiento_raises_when_patient_id_is_missing():
    with pytest.raises(DentalinkInvalidResponseError):
        treatment_from_tratamiento({"id": 1, "nombre": "Plan"})
