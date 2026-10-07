"""Get-or-create of the contact and conversation that identify one WhatsApp phone.

Shared by inbound ingestion and by the appointment-reminder worker so both
create the exact same rows (same id convention, same race handling).
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.exceptions.errors import ContactAlreadyExistsError, ConversationAlreadyExistsError
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber


def new_conversation_workflow_generation_seed(created_at: datetime) -> int:
    """Seeds a brand-new `Conversation` row's `workflow_session_generation`.

    T4 (R3-new-conversation-rotation-can-collide-with-prior-incarnation-
    generation): the domain entity's own dataclass default (a fixed `1`)
    makes a RECREATED conversation's checkpoint thread id
    (`f"{conversation_id}:session:N"`) fully deterministic across
    incarnations. If this exact conversation id (`ycloud-{phone}`) ever
    existed before — its row deleted and recreated, e.g. by tooling outside
    this application's own `ResetConversationUseCase` (which never deletes
    the row at all) — and a PRIOR incarnation ever reached that same
    generation number itself, the very next real turn would revive whatever
    checkpoint state (stage/pending_action_id) that old generation's thread
    still holds.

    `pending_actions` rows cannot carry this same risk on their own —
    `PendingActionModel.conversation_id` is a hard FK to `conversations.id`,
    so whatever deleted that row must already have cleared its pending
    actions first. Only the LangGraph checkpoint thread carries the real
    risk: this application has no FK/query relationship to it at all, so
    there is no reachable prior generation value to look up from data.

    Seeding from the current epoch second instead of a fixed default makes
    an accidental collision require the PRIOR incarnation to have rotated
    into the high hundreds of millions of generations — never reachable
    through this codebase's own rotation triggers. `workflow_session_generation`
    is already a `BigInteger` column (`ConversationModel`), so this needs no
    migration.
    """
    return int(created_at.timestamp())


async def resolve_or_create_contact(
    contact_repository: ContactRepository, phone: PhoneNumber
) -> Contact:
    contact = await contact_repository.get_by_phone(phone)
    if contact is not None:
        return contact
    contact = Contact(id=str(uuid4()), phone=phone, patient_id=None)
    try:
        await contact_repository.save(contact)
    except ContactAlreadyExistsError:
        # Race: another concurrent request for this same brand-new phone
        # number already created a contact row between our own get_by_phone
        # and save() (see that exception's own docstring). Re-read rather
        # than proceed with two contact records for the same person.
        existing = await contact_repository.get_by_phone(phone)
        if existing is not None:
            return existing
        # Flushed a moment too late for us to see it yet under READ
        # COMMITTED — provably about to exist with these exact fields
        # either way, so continue with our own in-memory copy rather than
        # fail the whole turn over a read-timing gap.
        return contact
    return contact


async def resolve_or_create_conversation(
    conversation_repository: ConversationRepository,
    phone: PhoneNumber,
    contact_id: str,
) -> tuple[Conversation, bool]:
    """Returns the conversation and whether THIS call created it.

    YCloud/WhatsApp conversations are 1:1 with the sender's phone number (no
    separate vendor conversation-id concept, unlike Chatwoot's ticket-style
    `conversation.id`) — so our ConversationId IS `ycloud-{phone}`, a
    deliberate zero-migration id-encoding convention, not a hack.

    The `bool` is the ONLY way to tell a conversation's first-ever turn apart
    from any later one — by the time any other code runs, the row this same
    call just saved is already indistinguishable from an old one. Ingestion
    uses it to fire the once-ever welcome message (PRD.md §7).
    """
    conversation_id = ConversationId(f"ycloud-{phone}")
    conversation = await conversation_repository.get_by_id(conversation_id)
    if conversation is not None:
        return conversation, False
    created_at = datetime.now(UTC)
    conversation = Conversation(
        id=conversation_id,
        contact_id=contact_id,
        mode="agent",
        created_at=created_at,
        workflow_session_generation=new_conversation_workflow_generation_seed(created_at),
    )
    try:
        await conversation_repository.save(conversation)
    except ConversationAlreadyExistsError:
        # Race: another concurrent request for this same brand-new contact
        # already created this conversation row between our own get_by_id
        # and save() (see that exception's own docstring) — seen live, this
        # crashed the whole webhook request outright with an unhandled
        # IntegrityError. Re-read and report it as NOT new: whichever
        # concurrent request actually won gets to send the once-ever
        # welcome message.
        existing = await conversation_repository.get_by_id(conversation_id)
        if existing is not None:
            return existing, False
        return conversation, False
    return conversation, True
