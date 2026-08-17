from redis.asyncio import Redis

from app.application.appointments.reschedule_appointment import RescheduleAppointmentUseCase
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.exceptions.errors import AppointmentSlotUnavailableError
from app.domain.repositories.gateways import AppointmentGateway
from app.infrastructure.redis.lock import LOCK_BLOCKING_TIMEOUT_SECONDS, redis_lock

_LOCK_PREFIX = "lock:appointment"


class RevalidateAndRescheduleAppointmentUseCase:
    """Locks, revalidates, and reschedules an appointment (PRD.md §11.1-11.2, §13).

    Mirrors `RevalidateAndCreateAppointmentUseCase` exactly — same lock key
    shape, same revalidate-then-execute sequence, same
    `AppointmentSlotUnavailableError` contract — the only difference is the
    final gateway call (`reschedule_appointment` instead of
    `create_appointment`). See that class's own docstring for the full
    rationale (lock scope, simplification, caller obligations).
    """

    def __init__(
        self,
        gateway: AppointmentGateway,
        redis_client: Redis,
        lock_blocking_timeout_seconds: float = LOCK_BLOCKING_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._redis_client = redis_client
        self._reschedule_appointment = RescheduleAppointmentUseCase(gateway)
        self._lock_blocking_timeout_seconds = lock_blocking_timeout_seconds

    async def execute(
        self, appointment_id: str, new_slot: AppointmentSlot, idempotency_key: str
    ) -> Appointment:
        lock_name = (
            f"{_LOCK_PREFIX}:{new_slot.professional_id}:{new_slot.time_range.start.isoformat()}"
        )

        async with redis_lock(
            self._redis_client,
            lock_name,
            blocking_timeout=self._lock_blocking_timeout_seconds,
        ) as acquired:
            if not acquired:
                raise AppointmentSlotUnavailableError(new_slot.id)

            still_available = await self._gateway.search_availability(
                specialty_id=new_slot.specialty_id,
                professional_id=new_slot.professional_id,
                date_range=new_slot.time_range,
            )
            if not any(candidate.id == new_slot.id for candidate in still_available):
                raise AppointmentSlotUnavailableError(new_slot.id)

            return await self._reschedule_appointment.execute(
                appointment_id, new_slot, idempotency_key
            )
