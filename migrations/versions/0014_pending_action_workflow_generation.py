"""Add workflow_generation to pending_actions and scheduled_actions.

The model gained this column in d3d76f6 (workflow-session rotation
expiry) but the migration was never amended — production hit
UndefinedColumnError on the first pending-action save after deploy.

Revision ID: 0014_pending_action_workflow_generation
Revises: 0013_awaiting_fresh_restart
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_pending_action_workflow_generation"
down_revision = "0013_awaiting_fresh_restart"


def upgrade() -> None:
    op.add_column(
        "pending_actions",
        sa.Column("workflow_generation", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scheduled_actions",
        sa.Column("workflow_generation", sa.BigInteger(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("scheduled_actions", "workflow_generation")
    op.drop_column("pending_actions", "workflow_generation")
