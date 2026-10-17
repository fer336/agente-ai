"""Meta's Click-to-WhatsApp welcome message is business-sent, not ours.

Assumption (the real payload is unverified): it may reach us as a
`whatsapp.smb.message.echoes` event seconds after the lead's first message. It
must not be read as a staff takeover, or every ad lead would land in human mode.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations.handle_smb_message_echo import (
    AD_WELCOME_ECHO_WINDOW,
    HandleSmbMessageEchoUseCase,
)
from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_ad_referral_repository import (
    FakeConversationAdReferralRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation

_PHONE = "+5491122334455"
_CONVERSATION_ID = ConversationId(f"ycloud-{_PHONE}")


async def _setup(
    *, referral_age: timedelta | None, mode: str = "agent"
) -> tuple[FakeConversationRepository, FakeConversationAdReferralRepository]:
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_=str(_CONVERSATION_ID), mode=mode))
    referrals = FakeConversationAdReferralRepository()
    if referral_age is not None:
        await referrals.save_if_new(
            ConversationAdReferral(
                id="r1",
                conversation_id=str(_CONVERSATION_ID),
                contact_id="contact-1",
                source_id="120239003788760630",
                source_type="ad",
                source_url=None,
                headline=None,
                ctwa_clid=None,
                raw={},
                first_seen_at=datetime.now(UTC) - referral_age,
                message_external_id="wamid.1",
            )
        )
    return conversations, referrals


async def _mode(conversations: FakeConversationRepository) -> str:
    conversation = await conversations.get_by_id(_CONVERSATION_ID)
    assert conversation is not None
    return conversation.mode


@pytest.mark.asyncio
async def test_echo_right_after_the_ad_first_message_does_not_pause_the_bot():
    conversations, referrals = await _setup(referral_age=timedelta(seconds=3))
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    ignored = await use_case.execute(_PHONE, is_reactivation_command=False)

    assert ignored is True
    assert await _mode(conversations) == "agent"
    conversation = await conversations.get_by_id(_CONVERSATION_ID)
    assert conversation is not None
    assert conversation.last_human_reply_at is None


@pytest.mark.asyncio
async def test_echo_after_the_window_still_pauses_the_bot():
    conversations, referrals = await _setup(
        referral_age=AD_WELCOME_ECHO_WINDOW + timedelta(seconds=5)
    )
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    ignored = await use_case.execute(_PHONE, is_reactivation_command=False)

    assert ignored is False
    assert await _mode(conversations) == "human"


@pytest.mark.asyncio
async def test_echo_without_any_referral_still_pauses_the_bot():
    conversations, referrals = await _setup(referral_age=None)
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    assert await use_case.execute(_PHONE, is_reactivation_command=False) is False
    assert await _mode(conversations) == "human"


@pytest.mark.asyncio
async def test_staff_commands_are_never_ignored_even_inside_the_window():
    conversations, referrals = await _setup(referral_age=timedelta(seconds=3))
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    ignored = await use_case.execute(_PHONE, is_reactivation_command=False, is_staff_command=True)

    assert ignored is False
    assert await _mode(conversations) == "human"


@pytest.mark.asyncio
async def test_reactivation_command_inside_the_window_still_works():
    conversations, referrals = await _setup(referral_age=timedelta(seconds=3), mode="human")
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    ignored = await use_case.execute(_PHONE, is_reactivation_command=True, is_staff_command=True)

    assert ignored is False
    assert await _mode(conversations) == "agent"


@pytest.mark.asyncio
async def test_without_a_referral_repository_behavior_is_unchanged():
    conversations, _ = await _setup(referral_age=timedelta(seconds=3))
    use_case = HandleSmbMessageEchoUseCase(conversations)

    assert await use_case.execute(_PHONE, is_reactivation_command=False) is False
    assert await _mode(conversations) == "human"


@pytest.mark.asyncio
async def test_referral_lookup_failure_falls_back_to_the_normal_pause():
    conversations, referrals = await _setup(referral_age=timedelta(seconds=3))

    async def boom(_conversation_id: ConversationId) -> None:
        raise RuntimeError("db down")

    referrals.get_latest_for_conversation = boom  # type: ignore[method-assign]
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    assert await use_case.execute(_PHONE, is_reactivation_command=False) is False
    assert await _mode(conversations) == "human"


@pytest.mark.asyncio
async def test_latest_referral_counts_so_a_second_ad_click_is_also_covered():
    conversations, referrals = await _setup(referral_age=timedelta(hours=2))
    await referrals.save_if_new(
        ConversationAdReferral(
            id="r2",
            conversation_id=str(_CONVERSATION_ID),
            contact_id="contact-1",
            source_id="another-ad",
            source_type="ad",
            source_url=None,
            headline=None,
            ctwa_clid=None,
            raw={},
            first_seen_at=datetime.now(UTC) - timedelta(seconds=2),
            message_external_id="wamid.2",
        )
    )
    use_case = HandleSmbMessageEchoUseCase(conversations, referrals)

    assert await use_case.execute(_PHONE, is_reactivation_command=False) is True
    assert await _mode(conversations) == "agent"
