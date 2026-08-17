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
