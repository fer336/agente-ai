from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.application.appointments.revalidate_and_create_appointment import (
    RevalidateAndCreateAppointmentUseCase,
)
from app.domain.exceptions.errors import AppointmentSlotUnavailableError
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import make_dentalink_gateway
from tests.fixtures.seed_objects import make_patient, make_slot


def _future_slot(id_: str = "slot-1", professional_id: str = "prof-1"):
    now = datetime.now(UTC)
    start = now + timedelta(days=1)
    return make_slot(
        id_=id_, professional_id=professional_id, start=start, end=start + timedelta(minutes=30)
    )


@pytest.mark.asyncio
async def test_execute_creates_the_appointment_when_slot_is_still_available():
    slot = _future_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    patient = make_patient()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, InMemoryFakeRedis())

    appointment = await use_case.execute(patient, slot, idempotency_key="key-1")

    assert appointment.slot == slot
    assert appointment.status == "confirmed"


@pytest.mark.asyncio
async def test_execute_raises_when_slot_is_no_longer_in_availability():
    slot = _future_slot()
    # Gateway configured WITHOUT the slot — simulates it being taken
    # between "mostrar opciones" and "confirmar" (PRD.md §11.2).
    gateway = make_dentalink_gateway(available_slots=[])
    patient = make_patient()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, InMemoryFakeRedis())

    with pytest.raises(AppointmentSlotUnavailableError) as exc_info:
        await use_case.execute(patient, slot, idempotency_key="key-1")

    assert exc_info.value.slot_id == slot.id


@pytest.mark.asyncio
async def test_execute_never_creates_when_slot_is_no_longer_available():
    slot = _future_slot()
    gateway = make_dentalink_gateway(available_slots=[])
    patient = make_patient()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, InMemoryFakeRedis())

    with pytest.raises(AppointmentSlotUnavailableError):
        await use_case.execute(patient, slot, idempotency_key="key-1")

    assert gateway.get_appointment("1") is None


@pytest.mark.asyncio
async def test_execute_raises_when_the_lock_is_already_held(monkeypatch: pytest.MonkeyPatch):
    slot = _future_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    patient = make_patient()
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndCreateAppointmentUseCase(
        gateway, redis_client, lock_blocking_timeout_seconds=0.05
    )
    lock_name = f"lock:appointment:{slot.professional_id}:{slot.time_range.start.isoformat()}"
    held_lock = redis_client.lock(lock_name)
    await held_lock.acquire()

    with pytest.raises(AppointmentSlotUnavailableError):
        await use_case.execute(patient, slot, idempotency_key="key-1")


@pytest.mark.asyncio
async def test_execute_revalidates_by_professional_never_by_specialty():
    # Against real Dentalink, `/v5/agendas` never returns `id_especialidad`,
    # so every slot it yields carries `specialty_id == ""` — and
    # `_propose_selected_slot` stamps the chosen specialty onto the slot
    # right before this runs. Revalidating with that stamped value matched
    # nothing and every confirmation died as "ese horario acaba de
    # ocuparse". The slot id is what identifies the slot; the specialty is
    # not a filter this step can use. The fake was kinder than production
    # here, which is exactly why the old test passed.
    slot = _future_slot(professional_id="prof-9")
    slot = replace(slot, specialty_id="cleaning")
    as_dentalink_returns_it = replace(slot, specialty_id="")
    gateway = make_dentalink_gateway(available_slots=[as_dentalink_returns_it])
    patient = make_patient()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, InMemoryFakeRedis())

    appointment = await use_case.execute(patient, slot, idempotency_key="key-1")

    assert appointment.slot == slot


@pytest.mark.asyncio
async def test_execute_releases_the_lock_after_successful_creation():
    slot = _future_slot()
    gateway = make_dentalink_gateway(available_slots=[slot])
    patient = make_patient()
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, redis_client)

    await use_case.execute(patient, slot, idempotency_key="key-1")

    assert redis_client.held_locks() == frozenset()


@pytest.mark.asyncio
async def test_execute_releases_the_lock_after_a_failed_revalidation():
    slot = _future_slot()
    gateway = make_dentalink_gateway(available_slots=[])
    patient = make_patient()
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndCreateAppointmentUseCase(gateway, redis_client)

    with pytest.raises(AppointmentSlotUnavailableError):
        await use_case.execute(patient, slot, idempotency_key="key-1")

    assert redis_client.held_locks() == frozenset()
