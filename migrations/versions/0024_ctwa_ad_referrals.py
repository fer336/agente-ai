"""click-to-whatsapp ad referrals

Stores the Meta ad a conversation started from (the `referral` object Meta
attaches to the first message of a lead that clicked a Click-to-WhatsApp ad).

Revision ID: 0024_ctwa_ad_referrals
Revises: 0023_agent_pause_filter
Create Date: 2026-10-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_ctwa_ad_referrals"
down_revision: str | None = "0023_agent_pause_filter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_ad_referrals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("contact_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("headline", sa.String(), nullable=True),
        sa.Column("ctwa_clid", sa.String(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_external_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_ad_referrals_conversation_id",
        "conversation_ad_referrals",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_ad_referrals_source_id", "conversation_ad_referrals", ["source_id"]
    )
    op.create_index(
        "ix_conversation_ad_referrals_first_seen_at",
        "conversation_ad_referrals",
        ["first_seen_at"],
    )
    op.create_index(
        "uq_conversation_ad_referrals_conversation_source",
        "conversation_ad_referrals",
        ["conversation_id", sa.text("coalesce(source_id, '')")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_conversation_ad_referrals_conversation_source", "conversation_ad_referrals")
    op.drop_index("ix_conversation_ad_referrals_first_seen_at", "conversation_ad_referrals")
    op.drop_index("ix_conversation_ad_referrals_source_id", "conversation_ad_referrals")
    op.drop_index("ix_conversation_ad_referrals_conversation_id", "conversation_ad_referrals")
    op.drop_table("conversation_ad_referrals")
