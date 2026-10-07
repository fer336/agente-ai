import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.dependencies.gateways import (
    get_reminder_appointment_gateway,
    get_reminder_patient_gateway,
)
from app.config.settings import Settings
from app.domain.value_objects.phone_number import PhoneNumber
from app.workers.appointment_reminder_worker import (
    AppointmentReminderWorkerRepositories,
    run_appointment_reminder_loop,
    run_appointment_reminder_tick,
)


@pytest.mark.asyncio
async def test_disabled_reminder_tick_makes_no_gateway_calls():
    repository = AsyncMock()
    appointments = AsyncMock()
    patients = AsyncMock()
    messaging = AsyncMock()

    result = await run_appointment_reminder_tick(
        repository,
        appointments,
        patients,
        messaging,
        Settings(_env_file=None),
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert result == (0, 0)
    assert appointments.method_calls == []
    assert patients.method_calls == []
    assert messaging.method_calls == []


@pytest.mark.asyncio
async def test_enabled_allowlisted_tick_uses_no_token_reminder_gateways_without_missing_methods(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.dependencies.gateways.get_settings", lambda: Settings(_env_file=None)
    )
    repository = AsyncMock()
    repository.list_due.return_value = []

    result = await run_appointment_reminder_tick(
        repository,
        get_reminder_appointment_gateway(),
        get_reminder_patient_gateway(),
        AsyncMock(),
        Settings(
            _env_file=None,
            appointment_reminders_enabled=True,
            appointment_reminders_phone_allowlist="+5491112345678",
        ),
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert result == (0, 0)


@pytest.mark.asyncio
async def test_enabled_all_tick_runs_without_an_allowlist():
    repository = AsyncMock()
    repository.list_due.return_value = []

    result = await run_appointment_reminder_tick(
        repository,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        Settings(
            _env_file=None,
            appointment_reminders_enabled=True,
            appointment_reminders_rollout_mode="all",
        ),
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert result == (0, 0)


@pytest.mark.asyncio
async def test_reminder_loop_repeats_survives_failures_and_propagates_cancellation(monkeypatch):
    repository = AsyncMock()
    calls = 0

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AppointmentReminderWorkerRepositories]:
        yield AppointmentReminderWorkerRepositories(reminders=repository, contacts=AsyncMock())

    async def tick(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return (2, 3)

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.run_appointment_reminder_tick", tick
    )

    settings = Settings(
        _env_file=None,
        appointment_reminders_enabled=True,
        appointment_reminders_phone_allowlist="+5491112345678",
    )
    await run_appointment_reminder_loop(
        repositories_provider,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        settings,
        interval_seconds=0,
        max_iterations=2,
    )

    assert calls == 2

    task = asyncio.create_task(
        run_appointment_reminder_loop(
            repositories_provider,
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            settings,
            interval_seconds=60,
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def _enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        appointment_reminders_enabled=True,
        appointment_reminders_rollout_mode="all",
    )


@pytest.mark.asyncio
async def test_tick_passes_a_fresh_session_hook_that_resets_the_patient_session(monkeypatch):
    captured = {}

    async def fake_deliver(*args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.deliver_due_reminders", fake_deliver
    )
    repository = AsyncMock()
    repository.list_due.return_value = []
    fresh_session = AsyncMock()
    phone = PhoneNumber("+5491112345678")

    await run_appointment_reminder_tick(
        repository,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        _enabled_settings(),
        start_fresh_session=fresh_session,
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )
    await captured["on_sent"](AsyncMock(), phone)

    fresh_session.execute.assert_awaited_once_with(phone)


@pytest.mark.asyncio
async def test_tick_without_a_fresh_session_use_case_passes_no_hook(monkeypatch):
    captured = {}

    async def fake_deliver(*args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.deliver_due_reminders", fake_deliver
    )
    repository = AsyncMock()
    repository.list_due.return_value = []

    await run_appointment_reminder_tick(
        repository,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        _enabled_settings(),
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert captured["on_sent"] is None


@pytest.mark.asyncio
async def test_loop_forwards_the_repositories_fresh_session_use_case(monkeypatch):
    fresh_session = AsyncMock()
    seen = {}

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AppointmentReminderWorkerRepositories]:
        yield AppointmentReminderWorkerRepositories(
            reminders=AsyncMock(), contacts=AsyncMock(), start_fresh_session=fresh_session
        )

    async def tick(*args, **kwargs):
        seen.update(kwargs)
        return (0, 0)

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.run_appointment_reminder_tick", tick
    )

    await run_appointment_reminder_loop(
        repositories_provider,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        _enabled_settings(),
        interval_seconds=0,
        max_iterations=1,
    )

    assert seen["start_fresh_session"] is fresh_session


@pytest.mark.asyncio
async def test_tick_forwards_the_record_sent_hook_to_delivery(monkeypatch):
    captured = {}

    async def fake_deliver(*args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.deliver_due_reminders", fake_deliver
    )
    repository = AsyncMock()
    repository.list_due.return_value = []
    record_sent = AsyncMock()

    await run_appointment_reminder_tick(
        repository,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        _enabled_settings(),
        record_sent=record_sent,
        now=datetime(2026, 10, 2, tzinfo=UTC),
    )

    assert captured["record_sent"] is record_sent


@pytest.mark.asyncio
async def test_loop_forwards_the_repositories_record_sent_hook(monkeypatch):
    record_sent = AsyncMock()
    seen = {}

    @asynccontextmanager
    async def repositories_provider() -> AsyncIterator[AppointmentReminderWorkerRepositories]:
        yield AppointmentReminderWorkerRepositories(
            reminders=AsyncMock(), contacts=AsyncMock(), record_sent=record_sent
        )

    async def tick(*args, **kwargs):
        seen.update(kwargs)
        return (0, 0)

    monkeypatch.setattr(
        "app.workers.appointment_reminder_worker.run_appointment_reminder_tick", tick
    )

    await run_appointment_reminder_loop(
        repositories_provider,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        _enabled_settings(),
        interval_seconds=0,
        max_iterations=1,
    )

    assert seen["record_sent"] is record_sent
