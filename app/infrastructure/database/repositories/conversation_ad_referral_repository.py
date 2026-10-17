from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.conversation_ad_referral import (
    ConversationAdReferralModel,
)


class SqlAlchemyConversationAdReferralRepository:
    """`ConversationAdReferralRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_if_new(self, referral: ConversationAdReferral) -> bool:
        model_class = ConversationAdReferralModel
        if await self._exists(referral):
            return False
        try:
            # A savepoint: a rejected row (concurrent duplicate, unknown conversation)
            # rolls back alone and leaves the caller's transaction usable.
            async with self._session.begin_nested():
                self._session.add(
                    model_class(
                        id=referral.id,
                        conversation_id=referral.conversation_id,
                        contact_id=referral.contact_id,
                        source_id=referral.source_id,
                        source_type=referral.source_type,
                        source_url=referral.source_url,
                        headline=referral.headline,
                        ctwa_clid=referral.ctwa_clid,
                        raw=referral.raw,
                        first_seen_at=referral.first_seen_at,
                        message_external_id=referral.message_external_id,
                    )
                )
                await self._session.flush()
        except IntegrityError:
            # Lost the race against a concurrent delivery of the same referral.
            if await self._exists(referral):
                return False
            raise
        return True

    async def get_first_for_conversation(
        self, conversation_id: ConversationId
    ) -> ConversationAdReferral | None:
        model_class = ConversationAdReferralModel
        model = await self._session.scalar(
            select(model_class)
            .where(model_class.conversation_id == str(conversation_id))
            .order_by(model_class.first_seen_at.asc())
            .limit(1)
        )
        if model is None:
            return None
        return ConversationAdReferral(
            id=model.id,
            conversation_id=model.conversation_id,
            contact_id=model.contact_id,
            source_id=model.source_id,
            source_type=model.source_type,
            source_url=model.source_url,
            headline=model.headline,
            ctwa_clid=model.ctwa_clid,
            raw=dict(model.raw),
            first_seen_at=model.first_seen_at,
            message_external_id=model.message_external_id,
        )

    async def _exists(self, referral: ConversationAdReferral) -> bool:
        model_class = ConversationAdReferralModel
        found = await self._session.scalar(
            select(model_class.id).where(
                model_class.conversation_id == referral.conversation_id,
                func.coalesce(model_class.source_id, "") == (referral.source_id or ""),
            )
        )
        return found is not None
