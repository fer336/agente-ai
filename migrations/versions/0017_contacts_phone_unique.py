"""contacts_phone_unique

Adds a real UNIQUE constraint on contacts.phone. Nothing here enforced it
before: `contacts.id` is a fresh UUID generated per creation attempt
(`IngestMessageUseCase._resolve_or_create_contact`), so it never collides
on its own — two concurrent webhook deliveries for the same brand-new
phone number could both pass the "does this phone already have a contact"
check before either committed, and both INSERT successfully, silently
creating two separate contact records for the same person (split contact
history, contact_memory, everything keyed off contact_id from then on).

Confirmed via a read-only production check before writing this: 2 total
contacts, 0 duplicate phone groups — safe to add without a prior
deduplication pass.

Revision ID: 0017_contacts_phone_unique
Revises: 0016_scheduled_action_nullable
Create Date: 2026-09-17

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017_contacts_phone_unique"
down_revision: str | None = "0016_scheduled_action_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "uq_contacts_phone"


def upgrade() -> None:
    op.create_unique_constraint(_CONSTRAINT_NAME, "contacts", ["phone"])


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "contacts", type_="unique")
