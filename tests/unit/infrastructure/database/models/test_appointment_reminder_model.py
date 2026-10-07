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
    assert any("confirm_day_before" in check and "review_request" in check for check in checks)
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


def test_appointment_reminder_table_stores_the_nullable_appointment_start():
    column = Base.metadata.tables["appointment_reminders"].c.appointment_starts_at

    assert column.nullable is True
    assert column.type.timezone is True


def test_appointment_start_migration_extends_the_review_opt_out_head():
    migration_path = (
        Path(__file__).parents[5] / "migrations/versions/0021_reminder_appointment_start.py"
    )
    spec = importlib.util.spec_from_file_location("reminder_appointment_start", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "0020_review_opt_out"
    assert migration.revision == "0021_reminder_appointment_start"


def test_appointment_reminder_table_has_no_foreign_keys_to_local_tables():
    table = Base.metadata.tables["appointment_reminders"]

    assert table.foreign_keys == set()


def test_drop_local_foreign_keys_migration_extends_the_appointment_start_head():
    migration_path = (
        Path(__file__).parents[5] / "migrations/versions/0022_reminder_drop_local_fks.py"
    )
    spec = importlib.util.spec_from_file_location("reminder_drop_local_fks", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "0021_reminder_appointment_start"
    assert migration.revision == "0022_reminder_drop_local_fks"
