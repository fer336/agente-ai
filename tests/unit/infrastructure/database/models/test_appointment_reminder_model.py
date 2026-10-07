import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.infrastructure.database.models import Base


def test_appointment_reminder_table_has_unique_appointment_kind_and_state_constraints():
    table = Base.metadata.tables["appointment_reminders"]

    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"appointment_id", "kind"}
        for constraint in table.constraints
    )
    checks = [
        constraint.sqltext.text
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert any(
        "confirm_day_before" in check and "review_request" in check for check in checks
    )
    assert any(
        "processing" in check and "skipped" in check and "failed" in check for check in checks
    )


def test_appointment_reminder_table_stores_retry_and_delivery_timestamps():
    table = Base.metadata.tables["appointment_reminders"]

    assert {"due_at", "claimed_at", "created_at", "updated_at", "sent_at"} <= set(table.c.keys())
    assert table.c.recipient_phone.nullable is False
    assert table.c.attempts.nullable is False


def test_migration_follows_current_head_and_creates_the_registered_table():
    migration_path = Path("migrations/versions/0019_appointment_reminder.py")
    spec = importlib.util.spec_from_file_location("appointment_reminder_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "0018_chatwoot_mapping"
    assert migration.revision == "0019_appointment_reminder"
