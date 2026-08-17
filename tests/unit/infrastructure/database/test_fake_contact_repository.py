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


def test_fake_contact_repository_satisfies_contact_repository_protocol():
    assert isinstance(FakeContactRepository(), ContactRepository)
