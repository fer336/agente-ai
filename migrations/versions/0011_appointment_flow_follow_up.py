"""appointment flow follow-up support

Loosens `scheduled_actions.pending_action_id` to nullable so a follow-up
for a patient stuck mid-flow (no `PendingAction` exists yet — that only
gets created once a slot/appointment reaches confirmation) can be
scheduled the same way `ProposeAppointmentUseCase`'s confirmation timeout
already is. Also adds the two indexes the inactivity-follow-up worker's
periodic barrido needs: one for `ScheduledActionRepository.get_due`'s
`WHERE status = 'scheduled' AND scheduled_for <= :now` scan, and one for
determining "who spoke last in this conversation" from `messages`.

Revision ID: 0011_appointment_flow_follow_up
Revises: 0010_conversational_memory
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_appointment_flow_follow_up"
down_revision: str | None = "0010_conversational_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "scheduled_actions", "pending_action_id", existing_type=sa.String(), nullable=True
    )
    op.create_index(
        "ix_scheduled_actions_status_scheduled_for",
        "scheduled_actions",
        ["status", "scheduled_for"],
    )
    op.create_index(
        "ix_messages_conversation_id_created_at", "messages", ["conversation_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages")
    op.drop_index("ix_scheduled_actions_status_scheduled_for", table_name="scheduled_actions")
    op.alter_column(
        "scheduled_actions", "pending_action_id", existing_type=sa.String(), nullable=False
    )
