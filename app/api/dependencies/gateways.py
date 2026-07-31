from functools import lru_cache

from app.domain.repositories.gateways import AppointmentGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway


@lru_cache
def _get_fake_dentalink_gateway() -> FakeDentalinkGateway:
    return FakeDentalinkGateway()


def get_appointment_gateway() -> AppointmentGateway:
    """FastAPI dependency providing the `AppointmentGateway` port.

    Returns the in-memory `FakeDentalinkGateway` for now. This is the swap
    point for a real Dentalink adapter in a later change — callers only
    depend on the `AppointmentGateway` Protocol.
    """
    return _get_fake_dentalink_gateway()
