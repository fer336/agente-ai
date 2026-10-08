"""Synthetic data for the isolated `/internal/eval/chat` stack only.

Never used by production wiring: `get_evaluate_chat_turn_use_case` builds a fresh
seed per eval conversation. Everything here is fictional (no real patient, no real
DNI or phone) and every id carries an `eval-` prefix so it can never collide with a
real Dentalink id in any shared cache key.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.entities.agreement import Agreement
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.value_objects.appointment_id import AppointmentId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.dentalink.fake_patient_gateway import FakePatientGateway
from app.infrastructure.dentalink.fake_specialty_gateway import FakeSpecialtyGateway

#: The known eval patient: two upcoming appointments. Datasets identify with these.
EVAL_PATIENT_NAME = "Lucía Prueba"
EVAL_PATIENT_DNI = "39000111"
_EVAL_PATIENT_ID = "eval-patient-1"
_EVAL_PATIENT_PHONE = PhoneNumber("+5490000000001")

_SPECIALTIES = [
    Specialty(id="eval-spec-1", name="Ortodoncia"),
    Specialty(id="eval-spec-2", name="Odontología general"),
    #: The specialty every consulta particular is booked on (clinic-topics-faq).
    Specialty(id="eval-spec-3", name="General"),
    #: The specialty the alineadores topic books on (clinic-topics-faq).
    Specialty(id="14", name="Alineadores Invisibles"),
]
_PROFESSIONALS = [
    Professional(id="eval-prof-1", full_name="Dra. Ana Ejemplo", specialty_id="eval-spec-1"),
    Professional(id="eval-prof-2", full_name="Dr. Bruno Muestra", specialty_id="eval-spec-2"),
    Professional(id="eval-prof-3", full_name="Dra. Carla Ejemplo", specialty_id="eval-spec-3"),
    Professional(id="eval-prof-4", full_name="Dr. Diego Muestra", specialty_id="14"),
]
#: Fictional agreements so "osde 210" resolves in the eval stack (first-visit intake and the
#: insurance lookup match the obra social name against this list).
_AGREEMENTS = [
    Agreement(id="eval-agr-1", name="OSDE"),
    Agreement(id="eval-agr-2", name="Swiss Medical"),
    Agreement(id="eval-agr-3", name="Galeno"),
]


@dataclass
class EvalSeed:
    dentalink: FakeDentalinkGateway
    patients: FakePatientGateway
    specialties: FakeSpecialtyGateway
    agreements: FakeAgreementGateway


def _slot(slot_id: str, professional: Professional, start: datetime) -> AppointmentSlot:
    assert professional.specialty_id is not None
    return AppointmentSlot(
        id=slot_id,
        professional_id=professional.id,
        specialty_id=professional.specialty_id,
        time_range=DateTimeRange(start, start + timedelta(minutes=30)),
    )


def build_eval_seed(now: datetime) -> EvalSeed:
    """A fresh seed relative to `now`, so the appointments are always upcoming."""
    day = now.replace(hour=10, minute=0, second=0, microsecond=0)
    booked = [
        Appointment(
            id=AppointmentId("eval-appt-1"),
            patient_id=_EVAL_PATIENT_ID,
            slot=_slot("eval-booked-1", _PROFESSIONALS[0], day + timedelta(days=3)),
            status="confirmed",
        ),
        Appointment(
            id=AppointmentId("eval-appt-2"),
            patient_id=_EVAL_PATIENT_ID,
            slot=_slot(
                "eval-booked-2",
                _PROFESSIONALS[1],
                (day + timedelta(days=8)).replace(hour=15, minute=30),
            ),
            status="confirmed",
        ),
    ]
    free = [
        _slot(f"eval-free-{index}", professional, day + timedelta(days=days))
        for index, (professional, days) in enumerate(
            [
                (_PROFESSIONALS[0], 5),
                (_PROFESSIONALS[0], 6),
                (_PROFESSIONALS[1], 5),
                (_PROFESSIONALS[2], 4),
                (_PROFESSIONALS[3], 4),
            ],
            start=1,
        )
    ]
    return EvalSeed(
        dentalink=FakeDentalinkGateway(
            available_slots=free, professionals=list(_PROFESSIONALS), appointments=booked
        ),
        patients=FakePatientGateway(
            [
                Patient(
                    id=_EVAL_PATIENT_ID,
                    full_name=EVAL_PATIENT_NAME,
                    phone=_EVAL_PATIENT_PHONE,
                    dni=EVAL_PATIENT_DNI,
                    email="lucia.prueba@example.com",
                )
            ]
        ),
        specialties=FakeSpecialtyGateway(list(_SPECIALTIES)),
        agreements=FakeAgreementGateway(list(_AGREEMENTS)),
    )
