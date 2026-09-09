"""conversation last_human_reply_at column

Adds `conversations.last_human_reply_at` (nullable timestamp), backing the
new message-command + lazy-timeout bot/human handoff mechanism that
replaces the YCloud tag-driven toggle (`SyncConversationModeFromTagUseCase`)
for accounts where tag PATCH calls don't persist (confirmed live against a
Coexistence-connected WhatsApp number: YCloud returns 200 OK but the tag
never sticks on the contact). See
`app.application.conversations.sync_conversation_mode_from_tag` and
`app.application.messages.ingest_message`'s lazy-timeout constant for the
two mechanisms this column now backs:

- Set on every `whatsapp.smb.message.echoes` webhook event YCloud delivers
  for a staff-sent WhatsApp Business App message while a conversation is
  `mode="human"`.
- Read by `IngestMessageUseCase.execute`'s human-mode gate to auto-flip
  `mode` back to `"agent"` once more than the configured threshold has
  elapsed since the last human reply.

Revision ID: 0011_conversation_last_human_reply_at
Revises: 0010_conversational_memory
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_conversation_last_human_reply_at"
down_revision: str | None = "0010_conversational_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_human_reply_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "last_human_reply_at")
