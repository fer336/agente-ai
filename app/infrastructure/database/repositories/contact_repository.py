from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.contact import Contact
from app.domain.exceptions.errors import ContactAlreadyExistsError
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
        is_insert = model is None
        if model is None:
            model = ContactModel(id=contact.id)
            self._session.add(model)

        model.phone = str(contact.phone)
        model.patient_id = contact.patient_id
        model.review_opted_out_at = contact.review_opted_out_at
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # `contacts.id` is a fresh UUID per creation attempt, so it
            # never collides — the only constraint an INSERT can hit here
            # is `uq_contacts_phone` (migration 0017), meaning a concurrent
            # request already created a contact for this exact phone.
            await self._session.rollback()
            if not is_insert:
                raise
            raise ContactAlreadyExistsError(str(contact.phone)) from exc

    async def mark_review_opt_out(self, phone: PhoneNumber, opted_out_at: datetime) -> bool:
        result = cast(
            CursorResult[object],
            await self._session.execute(
                update(ContactModel)
                .where(
                    ContactModel.phone == str(phone),
                    ContactModel.review_opted_out_at.is_(None),
                )
                .values(review_opted_out_at=opted_out_at)
            ),
        )
        if result.rowcount:
            return True
        existing_result = await self._session.execute(
            select(ContactModel.id).where(ContactModel.phone == str(phone))
        )
        return existing_result.scalar_one_or_none() is not None

    async def is_review_opted_out(self, phone: PhoneNumber) -> bool:
        result = await self._session.execute(
            select(ContactModel.review_opted_out_at).where(ContactModel.phone == str(phone))
        )
        return result.scalar_one_or_none() is not None


def _to_entity(model: ContactModel) -> Contact:
    return Contact(
        id=model.id,
        phone=PhoneNumber(model.phone),
        patient_id=model.patient_id,
        review_opted_out_at=model.review_opted_out_at,
    )
