from typing import Protocol, runtime_checkable

from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class ConversationAdReferralRepository(Protocol):
    """Port to the store of Click-to-WhatsApp ad referrals per conversation."""

    async def save_if_new(self, referral: ConversationAdReferral) -> bool:
        """Stores the referral unless the conversation already has one for the
        same `source_id` (a missing id counts as one shared value). Returns
        whether a row was inserted."""
        ...

    async def get_first_for_conversation(
        self, conversation_id: ConversationId
    ) -> ConversationAdReferral | None:
        """The earliest referral (by `first_seen_at`) of the conversation, if any."""
        ...
