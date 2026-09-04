"""runtime agent config

Creates the `runtime_agent_config` table (this session's own brief, no
PRD.md section number): one admin-editable row holding the model,
temperature, debounce seconds, and the three LLM prompts, so they can be
changed without a redeploy. No uniqueness constraint on `id` beyond it
being the primary key — get-or-create-on-write is enforced in
`SqlAlchemyRuntimeConfigRepository`, matching this codebase's existing
looseness on similar 1:1 tables (e.g. `admin_users`).

Revision ID: 0009_runtime_agent_config
Revises: 0008_incidents
Create Date: 2026-09-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_runtime_agent_config"
down_revision: str | None = "0008_incidents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)

    op.create_table(
        "runtime_agent_config",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("debounce_seconds", sa.Integer(), nullable=False),
        sa.Column("classify_intent_prompt", sa.Text(), nullable=False),
        sa.Column("extract_information_prompt", sa.Text(), nullable=False),
        sa.Column("generate_response_prompt", sa.Text(), nullable=False),
        sa.Column("updated_at", ts, nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("runtime_agent_config")
