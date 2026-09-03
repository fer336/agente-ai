from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
    PatientGateway,
    SpecialtyGateway,
)
from app.domain.value_objects.interactive_button import InteractiveButton


class ConformingAppointmentGateway:
    async def search_availability(self, specialty_id, professional_id, date_range):
        return []

    async def list_professionals(self, specialty_id=None):
        return []

    async def get_patient_appointments(self, patient_id):
        return []

    async def create_appointment(self, patient, slot, idempotency_key):
        raise NotImplementedError

    async def reschedule_appointment(self, appointment_id, new_slot, idempotency_key):
        raise NotImplementedError

    async def cancel_appointment(self, appointment_id, idempotency_key):
        raise NotImplementedError


class PartialAppointmentGateway:
    async def search_availability(self, specialty_id, professional_id, date_range):
        return []


def test_conforming_class_satisfies_appointment_gateway_protocol():
    assert isinstance(ConformingAppointmentGateway(), AppointmentGateway)


def test_partial_class_does_not_satisfy_appointment_gateway_protocol():
    assert not isinstance(PartialAppointmentGateway(), AppointmentGateway)


def test_conforming_class_satisfies_agreement_gateway_protocol():
    class ConformingAgreementGateway:
        async def list_agreements(self):
            return []

        async def find_agreement_by_name(self, name):
            return None

        async def get_patient_agreements(self, patient_id):
            return []

    assert isinstance(ConformingAgreementGateway(), AgreementGateway)


def test_partial_class_does_not_satisfy_agreement_gateway_protocol():
    class PartialAgreementGateway:
        async def list_agreements(self):
            return []

    assert not isinstance(PartialAgreementGateway(), AgreementGateway)


def test_conforming_class_satisfies_specialty_gateway_protocol():
    class ConformingSpecialtyGateway:
        async def list_specialties(self):
            return []

    assert isinstance(ConformingSpecialtyGateway(), SpecialtyGateway)


def test_partial_class_does_not_satisfy_specialty_gateway_protocol():
    class PartialSpecialtyGateway:
        async def other_method(self):
            pass

    assert not isinstance(PartialSpecialtyGateway(), SpecialtyGateway)


def test_conforming_class_satisfies_messaging_gateway_protocol():
    class ConformingMessagingGateway:
        async def send_text_message(self, to, text):
            return "external-id"

        async def send_buttons(self, to, text, buttons):
            return "external-id"

        async def get_contact_phone(self, ycloud_contact_id):
            return None

    assert isinstance(ConformingMessagingGateway(), MessagingGateway)


def test_class_missing_send_text_message_does_not_satisfy_messaging_gateway_protocol():
    class NonConformingMessagingGateway:
        async def other_method(self):
            pass

    assert not isinstance(NonConformingMessagingGateway(), MessagingGateway)


def test_class_missing_send_buttons_does_not_satisfy_messaging_gateway_protocol():
    class PartialMessagingGateway:
        async def send_text_message(self, to, text):
            return "external-id"

    assert not isinstance(PartialMessagingGateway(), MessagingGateway)


def test_conforming_class_satisfies_human_handoff_gateway_protocol():
    class ConformingHandoffGateway:
        async def request_handoff(self, conversation_id, reason):
            return None

    assert isinstance(ConformingHandoffGateway(), HumanHandoffGateway)


def test_class_missing_request_handoff_does_not_satisfy_human_handoff_gateway_protocol():
    class NonConformingHandoffGateway:
        async def other_method(self):
            pass

    assert not isinstance(NonConformingHandoffGateway(), HumanHandoffGateway)


def test_conforming_class_satisfies_patient_gateway_protocol():
    class ConformingPatientGateway:
        async def find_patient(self, full_name, dni):
            return None

        async def create_patient(self, full_name, dni, phone):
            raise NotImplementedError

    assert isinstance(ConformingPatientGateway(), PatientGateway)


def test_partial_class_does_not_satisfy_patient_gateway_protocol():
    class PartialPatientGateway:
        async def other_method(self):
            pass

    assert not isinstance(PartialPatientGateway(), PatientGateway)


def test_class_missing_create_patient_does_not_satisfy_patient_gateway_protocol():
    class MissingCreatePatientGateway:
        async def find_patient(self, full_name, dni):
            return None

    assert not isinstance(MissingCreatePatientGateway(), PatientGateway)


def test_interactive_button_holds_id_and_title():
    button = InteractiveButton(id="confirm", title="Confirmar")

    assert button.id == "confirm"
    assert button.title == "Confirmar"
