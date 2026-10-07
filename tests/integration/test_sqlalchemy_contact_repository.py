from datetime import UTC, datetime

from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.repositories.contact_repository import (
    SqlAlchemyContactRepository,
)


async def test_save_then_get_by_phone_round_trips_a_new_contact(db_session):
    repository = SqlAlchemyContactRepository(db_session)
    contact = Contact(id="contact-new-1", phone=PhoneNumber("+5491122334455"), patient_id=None)

    await repository.save(contact)
    fetched = await repository.get_by_phone(PhoneNumber("+5491122334455"))

    assert fetched is not None
    assert fetched.id == "contact-new-1"
    assert fetched.phone == PhoneNumber("+5491122334455")
    assert fetched.patient_id is None


async def test_get_by_phone_returns_none_when_missing(db_session):
    repository = SqlAlchemyContactRepository(db_session)

    fetched = await repository.get_by_phone(PhoneNumber("+5491100009999"))

    assert fetched is None


async def test_save_then_get_by_id_round_trips_a_new_contact(db_session):
    repository = SqlAlchemyContactRepository(db_session)
    contact = Contact(id="contact-new-2", phone=PhoneNumber("+5491122335566"), patient_id=None)

    await repository.save(contact)
    fetched = await repository.get_by_id("contact-new-2")

    assert fetched is not None
    assert fetched.phone == PhoneNumber("+5491122335566")


async def test_get_by_id_returns_none_when_missing(db_session):
    repository = SqlAlchemyContactRepository(db_session)

    assert await repository.get_by_id("missing") is None


async def test_saving_the_same_contact_id_twice_resolves_the_existing_contact(db_session):
    repository = SqlAlchemyContactRepository(db_session)
    contact = Contact(id="contact-existing-1", phone=PhoneNumber("+5491100002222"), patient_id=None)

    await repository.save(contact)
    await repository.save(contact)
    fetched = await repository.get_by_phone(PhoneNumber("+5491100002222"))

    assert fetched is not None
    assert fetched.id == "contact-existing-1"


async def test_review_opt_out_persists_idempotently_without_creating_missing_contacts(db_session):
    repository = SqlAlchemyContactRepository(db_session)
    phone = PhoneNumber("+5491100002222")
    opted_out_at = datetime(2026, 10, 2, 13, tzinfo=UTC)

    assert not await repository.mark_review_opt_out(phone, opted_out_at)
    assert not await repository.is_review_opted_out(phone)

    await repository.save(Contact(id="contact-opt-out-1", phone=phone, patient_id=None))

    assert await repository.mark_review_opt_out(phone, opted_out_at)
    assert await repository.mark_review_opt_out(phone, opted_out_at)
    assert await repository.is_review_opted_out(phone)
    fetched = await repository.get_by_phone(phone)
    assert fetched is not None
    assert fetched.review_opted_out_at == opted_out_at
