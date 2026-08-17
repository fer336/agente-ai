from datetime import UTC, datetime, timedelta

import pytest

from app.application.appointments.revalidate_and_reschedule_appointment import (
    RevalidateAndRescheduleAppointmentUseCase,
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
async def test_execute_reschedules_the_appointment_when_the_new_slot_is_still_available():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new")
    gateway = make_dentalink_gateway(available_slots=[new_slot])
    created = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="key-1"
    )
    use_case = RevalidateAndRescheduleAppointmentUseCase(gateway, InMemoryFakeRedis())

    rescheduled = await use_case.execute(str(created.id), new_slot, idempotency_key="key-2")

    assert rescheduled.slot == new_slot
    assert rescheduled.id == created.id


@pytest.mark.asyncio
async def test_execute_raises_when_the_new_slot_is_no_longer_available():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new")
    gateway = make_dentalink_gateway(available_slots=[])
    created = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="key-1"
    )
    use_case = RevalidateAndRescheduleAppointmentUseCase(gateway, InMemoryFakeRedis())

    with pytest.raises(AppointmentSlotUnavailableError) as exc_info:
        await use_case.execute(str(created.id), new_slot, idempotency_key="key-2")

    assert exc_info.value.slot_id == new_slot.id


@pytest.mark.asyncio
async def test_execute_raises_when_the_lock_is_already_held():
    new_slot = _future_slot(id_="slot-new")
    gateway = make_dentalink_gateway(available_slots=[new_slot])
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndRescheduleAppointmentUseCase(
        gateway, redis_client, lock_blocking_timeout_seconds=0.05
    )
    lock_name = (
        f"lock:appointment:{new_slot.professional_id}:{new_slot.time_range.start.isoformat()}"
    )
    held_lock = redis_client.lock(lock_name)
    await held_lock.acquire()

    with pytest.raises(AppointmentSlotUnavailableError):
        await use_case.execute("appt-1", new_slot, idempotency_key="key-2")


@pytest.mark.asyncio
async def test_execute_releases_the_lock_after_successful_reschedule():
    old_slot = _future_slot(id_="slot-old")
    new_slot = _future_slot(id_="slot-new")
    gateway = make_dentalink_gateway(available_slots=[new_slot])
    created = await gateway.create_appointment(
        patient=make_patient(id_="pat-1"), slot=old_slot, idempotency_key="key-1"
    )
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndRescheduleAppointmentUseCase(gateway, redis_client)

    await use_case.execute(str(created.id), new_slot, idempotency_key="key-2")

    assert redis_client.held_locks() == frozenset()


@pytest.mark.asyncio
async def test_execute_releases_the_lock_after_a_failed_revalidation():
    new_slot = _future_slot(id_="slot-new")
    gateway = make_dentalink_gateway(available_slots=[])
    redis_client = InMemoryFakeRedis()
    use_case = RevalidateAndRescheduleAppointmentUseCase(gateway, redis_client)

    with pytest.raises(AppointmentSlotUnavailableError):
        await use_case.execute("appt-1", new_slot, idempotency_key="key-2")

    assert redis_client.held_locks() == frozenset()
