"""agent pause switch and contact filter

Adds the global pause switch and the per-contact deny/allow list to the
single-row runtime agent config.

Revision ID: 0023_agent_pause_filter
Revises: 0022_reminder_drop_local_fks
Create Date: 2026-10-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_agent_pause_filter"
down_revision: str | None = "0022_reminder_drop_local_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runtime_agent_config",
        sa.Column("agent_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("runtime_agent_config", sa.Column("paused_by", sa.String(), nullable=True))
    op.add_column(
        "runtime_agent_config", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "runtime_agent_config",
        sa.Column("contact_filter_mode", sa.String(), nullable=False, server_default="off"),
    )
    op.add_column(
        "runtime_agent_config",
        sa.Column(
            "contact_filter_phones",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("runtime_agent_config", "contact_filter_phones")
    op.drop_column("runtime_agent_config", "contact_filter_mode")
    op.drop_column("runtime_agent_config", "paused_at")
    op.drop_column("runtime_agent_config", "paused_by")
    op.drop_column("runtime_agent_config", "agent_paused")
