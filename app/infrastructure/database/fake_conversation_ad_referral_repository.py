from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId


class FakeConversationAdReferralRepository:
    """In-memory fake implementing `ConversationAdReferralRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._rows: list[ConversationAdReferral] = []

    def all(self) -> list[ConversationAdReferral]:
        return list(self._rows)

    async def save_if_new(self, referral: ConversationAdReferral) -> bool:
        key = (referral.conversation_id, referral.source_id or "")
        if any((row.conversation_id, row.source_id or "") == key for row in self._rows):
            return False
        self._rows.append(referral)
        return True

    async def get_first_for_conversation(
        self, conversation_id: ConversationId
    ) -> ConversationAdReferral | None:
        rows = [row for row in self._rows if row.conversation_id == str(conversation_id)]
        return min(rows, key=lambda row: row.first_seen_at, default=None)
