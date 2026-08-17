"""scheduled actions and media processing jobs

Creates `scheduled_actions` (PRD.md §16.2 — follow-up/expiration scheduling
for pending actions, e.g. `appointment_confirmation_timeout`) and
`media_processing_jobs` (PRD.md §24.1/§33 — inbound audio download/
transcription job tracking; the worker that consumes these tables is not
built yet, this only prepares the schema).

Revision ID: 0003_scheduled_and_media_jobs
Revises: 0002_core_schema
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_scheduled_and_media_jobs"
down_revision: str | None = "0002_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.create_table(
        "scheduled_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column(
            "pending_action_id", sa.String(), sa.ForeignKey("pending_actions.id"), nullable=False
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("scheduled_for", ts, nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("cancelled_at", ts, nullable=True),
        sa.Column("executed_at", ts, nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_scheduled_actions_idempotency_key"),
    )

    op.create_table(
        "media_processing_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_id", sa.String(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("media_mime_type", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("completed_at", ts, nullable=True),
        sa.UniqueConstraint("message_id", name="uq_media_processing_jobs_message_id"),
    )


def downgrade() -> None:
    op.drop_table("media_processing_jobs")
    op.drop_table("scheduled_actions")
