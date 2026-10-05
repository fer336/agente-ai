from unittest.mock import Mock

from app.config.settings import Settings
from app.main import start_appointment_reminder_worker


def test_reminder_worker_starts_only_when_enabled_with_an_allowed_recipient_policy(monkeypatch):
    created = []
    monkeypatch.setattr(
        "app.main.asyncio.create_task", lambda coroutine: created.append(coroutine) or Mock()
    )

    assert start_appointment_reminder_worker(Settings(_env_file=None)) is None
    assert created == []

    task = start_appointment_reminder_worker(
        Settings(
            _env_file=None,
            appointment_reminders_enabled=True,
            appointment_reminders_phone_allowlist="+5491112345678",
        )
    )

    assert task is not None
    assert len(created) == 1
    created[0].close()

    all_task = start_appointment_reminder_worker(
        Settings(
            _env_file=None,
            appointment_reminders_enabled=True,
            appointment_reminders_rollout_mode="all",
        )
    )

    assert all_task is not None
    assert len(created) == 2
    created[1].close()
