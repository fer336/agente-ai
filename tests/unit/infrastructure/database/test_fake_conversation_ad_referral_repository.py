from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_ad_referral_repository import (
    FakeConversationAdReferralRepository,
)

_NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _referral(
    id_: str = "r1",
    conversation_id: str = "conv-1",
    source_id: str | None = "ad-1",
    first_seen_at: datetime = _NOW,
) -> ConversationAdReferral:
    return ConversationAdReferral(
        id=id_,
        conversation_id=conversation_id,
        contact_id="contact-1",
        source_id=source_id,
        source_type="ad",
        source_url=None,
        headline=None,
        ctwa_clid=None,
        raw={},
        first_seen_at=first_seen_at,
        message_external_id="wamid.1",
    )


@pytest.mark.asyncio
async def test_save_if_new_inserts_then_ignores_the_same_conversation_and_ad():
    repository = FakeConversationAdReferralRepository()

    assert await repository.save_if_new(_referral("r1")) is True
    assert await repository.save_if_new(_referral("r2")) is False
    assert len(repository.all()) == 1


@pytest.mark.asyncio
async def test_same_ad_on_another_conversation_is_a_new_row():
    repository = FakeConversationAdReferralRepository()

    await repository.save_if_new(_referral("r1", "conv-1"))

    assert await repository.save_if_new(_referral("r2", "conv-2")) is True


@pytest.mark.asyncio
async def test_missing_source_id_is_deduplicated_per_conversation():
    repository = FakeConversationAdReferralRepository()

    assert await repository.save_if_new(_referral("r1", source_id=None)) is True
    assert await repository.save_if_new(_referral("r2", source_id=None)) is False


@pytest.mark.asyncio
async def test_get_first_returns_the_earliest_referral_of_the_conversation():
    repository = FakeConversationAdReferralRepository()
    await repository.save_if_new(_referral("late", source_id="b", first_seen_at=_NOW))
    await repository.save_if_new(
        _referral("early", source_id="a", first_seen_at=_NOW - timedelta(minutes=5))
    )

    first = await repository.get_first_for_conversation(ConversationId("conv-1"))

    assert first is not None
    assert first.id == "early"
    assert await repository.get_first_for_conversation(ConversationId("other")) is None


@pytest.mark.asyncio
async def test_get_latest_returns_the_most_recent_referral_of_the_conversation():
    repository = FakeConversationAdReferralRepository()
    await repository.save_if_new(_referral("late", source_id="b", first_seen_at=_NOW))
    await repository.save_if_new(
        _referral("early", source_id="a", first_seen_at=_NOW - timedelta(minutes=5))
    )

    latest = await repository.get_latest_for_conversation(ConversationId("conv-1"))

    assert latest is not None
    assert latest.id == "late"
