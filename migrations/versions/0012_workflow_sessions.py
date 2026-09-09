"""Add rotatable workflow session lifecycle fields.

Revision ID: 0012_workflow_sessions
Revises: 0011_last_human_reply_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_workflow_sessions"
down_revision = "0011_last_human_reply_at"


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "workflow_session_generation", sa.BigInteger(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("workflow_last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "workflow_last_activity_at")
    op.drop_column("conversations", "workflow_session_generation")
