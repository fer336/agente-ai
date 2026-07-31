from app.domain.repositories.gateways import (
    AppointmentGateway,
    HumanHandoffGateway,
    MessagingGateway,
)


class ConformingAppointmentGateway:
    async def search_availability(self, specialty_id, professional_id, date_range):
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


def test_conforming_class_satisfies_messaging_gateway_protocol():
    class ConformingMessagingGateway:
        async def send_text_message(self, to, text):
            return "external-id"

    assert isinstance(ConformingMessagingGateway(), MessagingGateway)


def test_class_missing_send_text_message_does_not_satisfy_messaging_gateway_protocol():
    class NonConformingMessagingGateway:
        async def other_method(self):
            pass

    assert not isinstance(NonConformingMessagingGateway(), MessagingGateway)


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
