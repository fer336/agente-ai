"""`IngestMessageUseCase` stores the CTWA ad referral without ever blocking the message."""

import logging

import pytest

from app.application.messages.inbound_message_dto import AdReferralDTO, InboundMessageDTO
from app.domain.entities.conversation_ad_referral import ConversationAdReferral
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_conversation_ad_referral_repository import (
    FakeConversationAdReferralRepository,
)
from tests.fixtures.gateways import make_message_repository
from tests.unit.application.messages.test_ingest_message import _build_use_case

_PHONE = "+5491122334455"
_CONVERSATION_ID = ConversationId(f"ycloud-{_PHONE}")


def _dto(
    external_message_id: str = "wamid.ad-1",
    referral: AdReferralDTO | None = None,
) -> InboundMessageDTO:
    return InboundMessageDTO(
        external_message_id=external_message_id,
        from_phone=PhoneNumber(_PHONE),
        text="Hola, vi su anuncio",
        referral=referral,
    )


def _referral(source_id: str | None = "120239003788760630") -> AdReferralDTO:
    return AdReferralDTO(
        source_id=source_id,
        source_type="ad",
        source_url="https://fb.me/abc",
        headline="Limpieza dental",
        ctwa_clid="AR123",
        raw={"source_id": source_id},
    )


class _ExplodingRepository(FakeConversationAdReferralRepository):
    async def save_if_new(self, referral: ConversationAdReferral) -> bool:
        raise RuntimeError("database is down")


@pytest.mark.asyncio
async def test_referral_is_saved_once_for_the_conversation():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto(referral=_referral()))

    saved = await referrals.get_first_for_conversation(_CONVERSATION_ID)
    assert saved is not None
    assert saved.source_id == "120239003788760630"
    assert saved.ctwa_clid == "AR123"
    assert saved.message_external_id == "wamid.ad-1"
    assert saved.raw == {"source_id": "120239003788760630"}
    assert saved.contact_id


@pytest.mark.asyncio
async def test_second_message_with_the_same_ad_does_not_duplicate():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto("wamid.ad-1", _referral()))
    await use_case.execute(_dto("wamid.ad-2", _referral()))

    assert len(referrals.all()) == 1
    assert referrals.all()[0].message_external_id == "wamid.ad-1"


@pytest.mark.asyncio
async def test_redelivered_webhook_does_not_duplicate():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto("wamid.ad-1", _referral()))
    await use_case.execute(_dto("wamid.ad-1", _referral()))

    assert len(referrals.all()) == 1


@pytest.mark.asyncio
async def test_a_different_ad_on_the_same_conversation_adds_a_second_row():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto("wamid.ad-1", _referral("111")))
    await use_case.execute(_dto("wamid.ad-2", _referral("222")))

    assert sorted(r.source_id or "" for r in referrals.all()) == ["111", "222"]


@pytest.mark.asyncio
async def test_message_without_referral_saves_nothing():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto())

    assert referrals.all() == []


@pytest.mark.asyncio
async def test_referral_without_any_usable_content_saves_nothing():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)

    await use_case.execute(_dto(referral=AdReferralDTO()))

    assert referrals.all() == []


@pytest.mark.asyncio
async def test_referral_without_source_id_is_still_kept_once():
    referrals = FakeConversationAdReferralRepository()
    use_case = _build_use_case(ad_referral_repository=referrals)
    only_raw = AdReferralDTO(raw={"unknown_shape": {"x": 1}})

    await use_case.execute(_dto("wamid.ad-1", only_raw))
    await use_case.execute(_dto("wamid.ad-2", only_raw))

    assert len(referrals.all()) == 1
    assert referrals.all()[0].source_id is None


@pytest.mark.asyncio
async def test_use_case_without_a_referral_repository_still_ingests():
    message_repository = make_message_repository()
    use_case = _build_use_case(message_repository=message_repository)

    await use_case.execute(_dto(referral=_referral()))

    assert await message_repository.exists_by_external_id(ExternalMessageId("wamid.ad-1"))


@pytest.mark.asyncio
async def test_failure_to_store_the_referral_never_breaks_the_message(caplog):
    message_repository = make_message_repository()
    use_case = _build_use_case(
        message_repository=message_repository, ad_referral_repository=_ExplodingRepository()
    )

    with caplog.at_level(logging.WARNING):
        await use_case.execute(_dto(referral=_referral()))

    assert await message_repository.exists_by_external_id(ExternalMessageId("wamid.ad-1"))
    assert any("ad_referral" in record.getMessage() for record in caplog.records)
