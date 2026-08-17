from app.domain.entities.contact import Contact
from app.domain.value_objects.phone_number import PhoneNumber


class FakeContactRepository:
    """In-memory fake implementing `ContactRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._contacts_by_id: dict[str, Contact] = {}

    async def get_by_phone(self, phone: PhoneNumber) -> Contact | None:
        for contact in self._contacts_by_id.values():
            if contact.phone == phone:
                return contact
        return None

    async def get_by_id(self, contact_id: str) -> Contact | None:
        return self._contacts_by_id.get(contact_id)

    async def save(self, contact: Contact) -> None:
        self._contacts_by_id[contact.id] = contact
