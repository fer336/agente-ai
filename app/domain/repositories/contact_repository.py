from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber


@runtime_checkable
class ContactRepository(Protocol):
    """Port to durable storage for contacts."""

    async def get_by_phone(self, phone: PhoneNumber) -> Contact | None: ...

    async def get_by_id(self, contact_id: str) -> Contact | None: ...

    async def save(self, contact: Contact) -> None: ...

    async def mark_review_opt_out(self, phone: PhoneNumber, opted_out_at: datetime) -> bool:
        """Mark an existing contact as opted out; return False when it is absent."""
        ...

    async def is_review_opted_out(self, phone: PhoneNumber) -> bool: ...
