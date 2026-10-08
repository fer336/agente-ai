from datetime import UTC, datetime

import pytest

from app.domain.repositories.contact_repository import ContactRepository
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.fake_contact_repository import FakeContactRepository
from tests.fixtures.gateways import make_contact_repository
from tests.fixtures.seed_objects import make_contact


@pytest.mark.asyncio
async def test_save_then_get_by_phone_returns_the_saved_contact():
    repository = make_contact_repository()
    contact = make_contact(id_="contact-1", phone="+5491122334455")

    await repository.save(contact)
    fetched = await repository.get_by_phone(PhoneNumber("+5491122334455"))

    assert fetched is contact


@pytest.mark.asyncio
async def test_get_by_phone_returns_none_when_no_contact_matches():
    repository = make_contact_repository()
    await repository.save(make_contact(id_="contact-1", phone="+5491122334455"))

    fetched = await repository.get_by_phone(PhoneNumber("+5491100009999"))

    assert fetched is None


@pytest.mark.asyncio
async def test_save_then_get_by_id_returns_the_saved_contact():
    repository = make_contact_repository()
    contact = make_contact(id_="contact-1", phone="+5491122334455")

    await repository.save(contact)
    fetched = await repository.get_by_id("contact-1")

    assert fetched is contact


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_no_contact_matches():
    repository = make_contact_repository()

    assert await repository.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_mark_review_opt_out_is_idempotent_and_never_creates_a_contact():
    repository = make_contact_repository()
    phone = PhoneNumber("+5491122334455")
    opted_out_at = datetime(2026, 10, 2, 13, tzinfo=UTC)

    assert not await repository.mark_review_opt_out(phone, opted_out_at)
    assert not await repository.is_review_opted_out(phone)

    await repository.save(make_contact(id_="contact-1", phone=str(phone)))

    assert await repository.mark_review_opt_out(phone, opted_out_at)
    assert await repository.mark_review_opt_out(phone, opted_out_at)
    assert await repository.is_review_opted_out(phone)
    assert (await repository.get_by_phone(phone)).review_opted_out_at == opted_out_at


def test_fake_contact_repository_satisfies_contact_repository_protocol():
    assert isinstance(FakeContactRepository(), ContactRepository)
