from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.models.contact import ContactModel


class SqlAlchemyContactRepository:
    """`ContactRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, phone: PhoneNumber) -> Contact | None:
        result = await self._session.execute(
            select(ContactModel).where(ContactModel.phone == str(phone))
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_entity(model)

    async def get_by_id(self, contact_id: str) -> Contact | None:
        model = await self._session.get(ContactModel, contact_id)
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, contact: Contact) -> None:
        model = await self._session.get(ContactModel, contact.id)
        if model is None:
            model = ContactModel(id=contact.id)
            self._session.add(model)

        model.phone = str(contact.phone)
        model.patient_id = contact.patient_id
        await self._session.flush()


def _to_entity(model: ContactModel) -> Contact:
    return Contact(
        id=model.id,
        phone=PhoneNumber(model.phone),
        patient_id=model.patient_id,
    )
