from app.api.dependencies.gateways import get_appointment_gateway
from app.domain.repositories.gateways import AppointmentGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


def test_get_appointment_gateway_returns_a_fake_dentalink_gateway():
    gateway = get_appointment_gateway()

    assert isinstance(gateway, FakeDentalinkGateway)
    assert isinstance(gateway, AppointmentGateway)


def test_get_appointment_gateway_returns_the_same_cached_instance_across_calls():
    first = get_appointment_gateway()
    second = get_appointment_gateway()

    assert first is second
