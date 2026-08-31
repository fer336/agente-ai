"""audio/transcription columns on messages

Adds the `messages.media_*`/`transcription_*` columns (PRD.md §33) needed by
the audio pipeline (PRD.md §24.1, §74.7): an inbound `type="audio"` message
is persisted with its media metadata immediately, then updated in place once
`TranscribeAudioUseCase` (running in the audio worker, PRD.md §65) produces a
transcript or a terminal failure/rejection.

Revision ID: 0006_audio_transcription
Revises: 0005_observability
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_audio_transcription"
down_revision: str | None = "0005_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("message_type", sa.String(), nullable=False, server_default="text"),
    )
    op.add_column("messages", sa.Column("media_id", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("media_mime_type", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("media_sha256", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("media_status", sa.String(), nullable=True))
    op.add_column(
        "messages", sa.Column("inbound_received_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("messages", sa.Column("transcription", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("transcription_status", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("transcription_provider", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("transcription_model", sa.String(), nullable=True))
    op.add_column(
        "messages", sa.Column("transcription_duration_ms", sa.Integer(), nullable=True)
    )
    op.add_column("messages", sa.Column("transcription_error", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "transcription_error")
    op.drop_column("messages", "transcription_duration_ms")
    op.drop_column("messages", "transcription_model")
    op.drop_column("messages", "transcription_provider")
    op.drop_column("messages", "transcription_status")
    op.drop_column("messages", "transcription")
    op.drop_column("messages", "inbound_received_at")
    op.drop_column("messages", "media_status")
    op.drop_column("messages", "media_sha256")
    op.drop_column("messages", "media_mime_type")
    op.drop_column("messages", "media_id")
    op.drop_column("messages", "message_type")
