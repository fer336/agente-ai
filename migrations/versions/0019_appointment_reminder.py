"""appointment_reminder

Creates durable delivery rows for idempotent appointment reminders. The
appointment/kind uniqueness is the scheduler's idempotency boundary, while
patient and recipient fields let a claimed row retry without re-reading a
mutable appointment payload.

Revision ID: 0019_appointment_reminder
Revises: 0018_chatwoot_mapping
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_appointment_reminder"
down_revision: str | None = "0018_chatwoot_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointment_reminders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("appointment_id", sa.String(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_phone", sa.String(), nullable=False),
        sa.Column("external_message_id", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "appointment_id",
            "kind",
            name="uq_appointment_reminders_appointment_kind",
        ),
        sa.CheckConstraint(
            "kind IN ('confirm_day_before', 'confirm_or_location_same_day', 'review_request')",
            name="ck_appointment_reminders_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'skipped', 'failed')",
            name="ck_appointment_reminders_status",
        ),
    )
    op.create_index(
        "ix_appointment_reminders_due_pending",
        "appointment_reminders",
        ["status", "due_at"],
    )
    op.create_index(
        "ix_appointment_reminders_patient_review_sent",
        "appointment_reminders",
        ["patient_id", "kind", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_appointment_reminders_patient_review_sent",
        table_name="appointment_reminders",
    )
    op.drop_index("ix_appointment_reminders_due_pending", table_name="appointment_reminders")
    op.drop_table("appointment_reminders")
