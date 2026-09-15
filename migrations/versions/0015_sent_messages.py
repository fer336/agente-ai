"""sent_messages

Creates the `sent_messages` table: correlates a YCloud outbound message id
to the conversation it was sent for, so an async `whatsapp.message.updated`
delivery-failure webhook can be attributed to a conversation/patient
instead of vanishing silently (that event carries YCloud's own message id
and an opaque `recipientUserId` — NOT a phone number — nothing else to
attribute the failure to).

Revision ID: 0015_sent_messages
Revises: 0014_pending_action_generation
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_sent_messages"
down_revision: str | None = "0014_pending_action_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sent_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sent_messages_conversation_id", "sent_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_sent_messages_conversation_id", table_name="sent_messages")
    op.drop_table("sent_messages")
