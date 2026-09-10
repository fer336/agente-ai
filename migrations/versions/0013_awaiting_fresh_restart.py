"""Add the awaiting_fresh_restart reactivation flag to conversations.

Revision ID: 0013_awaiting_fresh_restart
Revises: 0012_workflow_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_awaiting_fresh_restart"
down_revision = "0012_workflow_sessions"


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("awaiting_fresh_restart", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("conversations", "awaiting_fresh_restart")
