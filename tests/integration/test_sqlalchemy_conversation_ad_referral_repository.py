from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.models.conversation_ad_referral import (
    ConversationAdReferralModel,
)
from app.infrastructure.database.repositories.conversation_ad_referral_repository import (
    SqlAlchemyConversationAdReferralRepository,
)

_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _referral(
    id_: str,
    conversation_id: str,
    source_id: str | None = "120239003788760630",
    first_seen_at: datetime = _NOW,
) -> ConversationAdReferral:
    return ConversationAdReferral(
        id=id_,
        conversation_id=conversation_id,
        contact_id="contact-fixture",
        source_id=source_id,
        source_type="ad",
        source_url="https://fb.me/abc",
        headline="Limpieza dental",
        ctwa_clid="AR123",
        raw={"source_id": source_id, "nested": {"a": [1, 2]}},
        first_seen_at=first_seen_at,
        message_external_id="wamid.1",
    )


async def _count(db_session) -> int:
    rows = await db_session.execute(select(ConversationAdReferralModel))
    return len(rows.scalars().all())


async def test_save_if_new_persists_and_round_trips_the_raw_object(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)

    assert await repository.save_if_new(_referral("r1", conversation_id)) is True
    fetched = await repository.get_first_for_conversation(ConversationId(conversation_id))

    assert fetched is not None
    assert fetched.source_id == "120239003788760630"
    assert fetched.ctwa_clid == "AR123"
    assert fetched.raw == {"source_id": "120239003788760630", "nested": {"a": [1, 2]}}
    assert fetched.first_seen_at == _NOW


async def test_same_conversation_and_ad_is_idempotent(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)

    assert await repository.save_if_new(_referral("r1", conversation_id)) is True
    assert await repository.save_if_new(_referral("r2", conversation_id)) is False

    assert await _count(db_session) == 1


async def test_different_ad_on_the_same_conversation_adds_a_row(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)

    await repository.save_if_new(_referral("r1", conversation_id, "111"))
    assert await repository.save_if_new(_referral("r2", conversation_id, "222")) is True

    assert await _count(db_session) == 2


async def test_missing_source_id_is_deduplicated(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)

    assert await repository.save_if_new(_referral("r1", conversation_id, None)) is True
    assert await repository.save_if_new(_referral("r2", conversation_id, None)) is False


async def test_a_failed_insert_does_not_poison_the_session(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)

    # Unknown conversation: the foreign key rejects the row.
    try:
        await repository.save_if_new(_referral("r-bad", "no-such-conversation"))
    except Exception:
        pass

    assert await repository.save_if_new(_referral("r1", conversation_id)) is True


async def test_get_first_returns_the_earliest(db_session, conversation_id):
    repository = SqlAlchemyConversationAdReferralRepository(db_session)
    await repository.save_if_new(_referral("late", conversation_id, "b", _NOW))
    await repository.save_if_new(
        _referral("early", conversation_id, "a", _NOW - timedelta(minutes=5))
    )

    first = await repository.get_first_for_conversation(ConversationId(conversation_id))

    assert first is not None
    assert first.id == "early"
