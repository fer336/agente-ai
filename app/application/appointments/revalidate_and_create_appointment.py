from redis.asyncio import Redis

from app.application.appointments.create_appointment import CreateAppointmentUseCase
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.exceptions.errors import AppointmentSlotUnavailableError
from app.domain.repositories.gateways import AppointmentGateway
from app.infrastructure.redis.lock import LOCK_BLOCKING_TIMEOUT_SECONDS, redis_lock

_LOCK_PREFIX = "lock:appointment"


class RevalidateAndCreateAppointmentUseCase:
    """Locks, revalidates, and creates an appointment (PRD.md §11.1-11.2).

    Never creates without this exact sequence: acquire a short Redis lock
    keyed by professional + slot start time (PRD.md §11.1's
    `lock:appointment:{sucursal}:{profesional}:{fecha}:{hora}:{recurso}`
    pattern, simplified to `lock:appointment:{professional_id}:{start_isoformat}`
    — `AppointmentSlot` carries no sucursal/sillón data, matching the same
    single-clinic simplification already made in `DentalinkAppointmentGateway`,
    see that change's report), revalidate the slot is STILL among
    `AppointmentGateway.search_availability`'s options, then create.

    Reuses `app.infrastructure.redis.lock.redis_lock` — the exact same
    generic, string-keyed primitive `IngestMessageUseCase` already uses for
    its own per-conversation lock (Etapa 4 PR3) — rather than a new lock
    mechanism.

    Raises `AppointmentSlotUnavailableError` (PRD.md §11.2: "Ese horario
    acaba de ocuparse mientras confirmábamos") when the lock can't be
    acquired OR revalidation finds the slot gone. The lock protects only
    against concurrent executions of THIS application (PRD.md §11.1's own
    caveat: "No impide que recepción reserve directamente en Dentalink") —
    revalidation against Dentalink itself is what actually matters; the
    lock only prevents two of our own conversations from racing each
    other into a duplicate revalidate-then-create window for the exact
    same slot. Callers must never retry the same slot automatically on
    this error, only offer new options.
    """

    def __init__(
        self,
        gateway: AppointmentGateway,
        redis_client: Redis,
        lock_blocking_timeout_seconds: float = LOCK_BLOCKING_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._redis_client = redis_client
        self._create_appointment = CreateAppointmentUseCase(gateway)
        self._lock_blocking_timeout_seconds = lock_blocking_timeout_seconds

    async def execute(
        self, patient: Patient, slot: AppointmentSlot, idempotency_key: str
    ) -> Appointment:
        lock_name = f"{_LOCK_PREFIX}:{slot.professional_id}:{slot.time_range.start.isoformat()}"

        async with redis_lock(
            self._redis_client,
            lock_name,
            blocking_timeout=self._lock_blocking_timeout_seconds,
        ) as acquired:
            if not acquired:
                raise AppointmentSlotUnavailableError(slot.id)

            still_available = await self._gateway.search_availability(
                specialty_id=slot.specialty_id,
                professional_id=slot.professional_id,
                date_range=slot.time_range,
            )
            if not any(candidate.id == slot.id for candidate in still_available):
                raise AppointmentSlotUnavailableError(slot.id)

            return await self._create_appointment.execute(patient, slot, idempotency_key)
