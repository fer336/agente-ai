"""chatwoot_conversation_mapping

Creates the `chatwoot_conversation_mappings` table: correlates our own
`conversation_id` to the Chatwoot contact/conversation it mirrors into,
since Chatwoot's API has no idempotent "find or create conversation"
endpoint — without tracking the returned id ourselves, every mirrored
turn would spawn a new Chatwoot conversation instead of continuing the
same thread.

Revision ID: 0018_chatwoot_conversation_mapping
Revises: 0017_contacts_phone_unique
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018_chatwoot_conversation_mapping"
down_revision: str | None = "0017_contacts_phone_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chatwoot_conversation_mappings",
        sa.Column("conversation_id", sa.String(), primary_key=True),
        sa.Column("chatwoot_contact_id", sa.String(), nullable=False),
        sa.Column("chatwoot_conversation_id", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chatwoot_conversation_mappings")
