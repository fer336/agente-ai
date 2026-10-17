from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.infrastructure.database.models.base import Base


class ConversationAdReferralModel(Base):
    """Row shape for `conversation_ad_referrals`: the Click-to-WhatsApp ad a
    conversation came from, see `app.domain.entities.conversation_ad_referral`."""

    __tablename__ = "conversation_ad_referrals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    headline: Mapped[str | None] = mapped_column(String, nullable=True)
    ctwa_clid: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    message_external_id: Mapped[str | None] = mapped_column(String, nullable=True)


#: One row per (conversation, ad); a missing ad id counts as one shared value.
Index(
    "uq_conversation_ad_referrals_conversation_source",
    ConversationAdReferralModel.conversation_id,
    func.coalesce(ConversationAdReferralModel.source_id, ""),
    unique=True,
)
