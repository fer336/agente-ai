"""reminder drop local foreign keys

Reminder rows carry Dentalink external appointment and patient ids. Appointments
and patients live in Dentalink and nothing creates local rows for them, so the
foreign keys to the local tables rejected every insert.

Revision ID: 0022_reminder_drop_local_fks
Revises: 0021_reminder_appointment_start
Create Date: 2026-10-07

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_reminder_drop_local_fks"
down_revision: str | None = "0021_reminder_appointment_start"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "appointment_reminders_appointment_id_fkey",
        "appointment_reminders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "appointment_reminders_patient_id_fkey",
        "appointment_reminders",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "appointment_reminders_appointment_id_fkey",
        "appointment_reminders",
        "appointments",
        ["appointment_id"],
        ["id"],
    )
    op.create_foreign_key(
        "appointment_reminders_patient_id_fkey",
        "appointment_reminders",
        "patients",
        ["patient_id"],
        ["id"],
    )
