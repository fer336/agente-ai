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
