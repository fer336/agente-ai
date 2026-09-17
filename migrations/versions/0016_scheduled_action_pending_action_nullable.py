"""scheduled_action_pending_action_nullable

Relaxes `scheduled_actions.pending_action_id` to nullable, matching the
SQLAlchemy model (`app/infrastructure/database/models/scheduled_action.py`)
and domain entity (`app/domain/entities/scheduled_action.py`), which have
always declared it `str | None` — this table's original migration
(0003_scheduled_and_media_jobs) set it `nullable=False`, a schema/model
mismatch that stayed silently harmless until PR #102 wired
`ScheduleFollowUpUseCase.reconcile()` into the live pipeline: it schedules
an `appointment_flow_follow_up_prompt` action with `pending_action_id=None`
on every turn that leaves a trámite mid-flow (deliberately — a follow-up
prompt can fire well before any `PendingAction` exists), which the real
constraint then rejected outright: seen live, every single inbound message
that reached an active stage started failing with
`NotNullViolationError: null value in column "pending_action_id"`.

Revision ID: 0016_scheduled_action_pending_nullable
Revises: 0015_sent_messages
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_scheduled_action_pending_nullable"
down_revision: str | None = "0015_sent_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "scheduled_actions",
        "pending_action_id",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "scheduled_actions",
        "pending_action_id",
        existing_type=sa.String(),
        nullable=False,
    )
