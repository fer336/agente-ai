from app.domain.entities.patient import Patient
from app.domain.value_objects.phone_number import PhoneNumber


def test_creates_patient_with_id_name_and_phone():
    patient = Patient(
        id="patient-1",
        full_name="Ana Gomez",
        phone=PhoneNumber(value="+5491122334455"),
    )

    assert patient.id == "patient-1"
    assert patient.full_name == "Ana Gomez"
    assert patient.phone == PhoneNumber(value="+5491122334455")


def test_patients_with_same_fields_are_equal():
    phone = PhoneNumber(value="+5491100000000")
    first = Patient(id="patient-2", full_name="Luis Diaz", phone=phone)
    second = Patient(id="patient-2", full_name="Luis Diaz", phone=phone)

    assert first == second


def test_patients_with_different_ids_are_not_equal():
    phone = PhoneNumber(value="+5491100000000")
    first = Patient(id="patient-3", full_name="Luis Diaz", phone=phone)
    second = Patient(id="patient-4", full_name="Luis Diaz", phone=phone)

    assert first != second
