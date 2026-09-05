"""conversational memory

Adds the conversational-memory module's schema (no PRD.md section number —
this is this session's own brief, not a PRD-driven change):

- `messages.role`: additive column for the existing `messages` table (Layer
  1, "persistent history"). Left NULL for pre-existing rows — `direction`
  already disambiguates them (`Message`'s own docstring / `MemoryService`'s
  `_message_role` fallback).
- `contact_memories`: one row per contact, holding the incrementally-updated
  compacted summary (Layer 3) — `contact_id` is indexed but not
  DB-uniqueness-constrained (get-or-create-on-write is enforced in
  `MemoryService`/`SqlAlchemyContactMemoryRepository`, matching this
  codebase's existing looseness on similar 1:1-in-practice tables, e.g.
  `admin_users`).

Layer 2 ("recent window") and Layer 4 ("current operational state") need no
new schema: Layer 2 is a bounded read of the existing `messages` table, and
Layer 4 is already fully covered by `AgentState` + the `AsyncPostgresSaver`
checkpointer.

Revision ID: 0010_conversational_memory
Revises: 0009_runtime_agent_config
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_conversational_memory"
down_revision: str | None = "0009_runtime_agent_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("role", sa.String(), nullable=True))

    ts = sa.DateTime(timezone=True)
    op.create_table(
        "contact_memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("contact_id", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_compacted_message_id", sa.String(), nullable=True),
        sa.Column("last_compacted_at", ts, nullable=True),
        sa.Column("updated_at", ts, nullable=False),
    )
    op.create_index("ix_contact_memories_contact_id", "contact_memories", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_contact_memories_contact_id", table_name="contact_memories")
    op.drop_table("contact_memories")
    op.drop_column("messages", "role")
