"""review opt out

Adds the durable preference that suppresses Google review requests while
leaving appointment reminders eligible.

Revision ID: 0020_review_opt_out
Revises: 0019_appointment_reminder
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_review_opt_out"
down_revision: str | None = "0019_appointment_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("review_opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "review_opted_out_at")
