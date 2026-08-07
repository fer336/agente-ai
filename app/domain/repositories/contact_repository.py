from typing import Protocol, runtime_checkable

from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber


@runtime_checkable
class ContactRepository(Protocol):
    """Port to durable storage for contacts."""

    async def get_by_phone(self, phone: PhoneNumber) -> Contact | None: ...

    async def save(self, contact: Contact) -> None: ...
