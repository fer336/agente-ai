from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber


def test_creates_contact_with_id_phone_and_optional_patient_id():
    contact = Contact(
        id="contact-1", phone=PhoneNumber(value="+5491122334455"), patient_id="patient-1"
    )

    assert contact.id == "contact-1"
    assert contact.phone == PhoneNumber(value="+5491122334455")
    assert contact.patient_id == "patient-1"


def test_contact_can_have_no_linked_patient():
    contact = Contact(id="contact-2", phone=PhoneNumber(value="+5491122334455"), patient_id=None)

    assert contact.patient_id is None
