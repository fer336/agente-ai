from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.workers.appointment_reminder_worker import run_appointment_reminder_tick


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
    appointments.method_calls == []
    patients.method_calls == []
    messaging.method_calls == []
