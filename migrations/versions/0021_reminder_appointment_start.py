"""reminder appointment start

Stores the appointment start on each reminder row so reply context and the idle
session cleanup can tell whether a sent reminder is still pending without an
external appointment read.

Revision ID: 0021_reminder_appointment_start
Revises: 0020_review_opt_out
Create Date: 2026-10-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_reminder_appointment_start"
down_revision: str | None = "0020_review_opt_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointment_reminders",
        sa.Column("appointment_starts_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appointment_reminders", "appointment_starts_at")
