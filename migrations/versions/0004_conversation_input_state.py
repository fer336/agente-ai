"""conversation input_state column

Adds `conversations.input_state` (PRD.md §6/§24.2:
FREE_INPUT/INTERACTIVE_SELECTION/SENSITIVE_CONFIRMATION/HUMAN) — a
separate concern from `conversations.mode` (PRD.md §23), which governs
whether LangGraph responds at all. `input_state` governs which KINDS of
inbound message (button vs free text/audio) may advance the conversation
right now.

Revision ID: 0004_conversation_input_state
Revises: 0003_scheduled_and_media_jobs
Create Date: 2026-08-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_conversation_input_state"
down_revision: str | None = "0003_scheduled_and_media_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "input_state", sa.String(), nullable=False, server_default="FREE_INPUT"
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "input_state")
