from app.application.memory.memory_service import MemoryService
from app.domain.repositories.contact_memory_repository import ContactMemoryRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.message_repository import MessageRepository

#: PRD's own brief has no dedicated default poll batch size for this worker
#: (conversational-memory module) — mirrors `app.workers.audio_tasks`'s own
#: small-batch-per-tick choice for the same reason (never monopolize the
#: LLM provider's rate limit with one sweep).
_DEFAULT_BATCH_SIZE = 10


async def compact_stale_contact_memories(
    conversation_repository: ConversationRepository,
    contact_memory_repository: ContactMemoryRepository,
    message_repository: MessageRepository,
    memory_service: MemoryService,
    threshold: int,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """One poll tick: compacts every contact (among the `batch_size` most
    recently active conversations) whose not-yet-compacted message count
    exceeds `threshold`.

    DELIBERATELY NOT a running process/scheduler — mirrors the exact same
    accepted gap as `app.workers.audio_tasks.process_pending_audio_jobs`
    and `app.workers.incident_tasks.check_incident_recovery`. This function
    is the complete, tested, swap-point-ready processing step; wiring it
    into an actual worker/cron entrypoint is a later, broader concern.

    Iterates via `ConversationRepository.list_recent` (a full-scan-at-
    MVP-scale read, same posture as `check_incident_recovery`'s own
    `list_open()` sweep) rather than a dedicated "list all contacts" method
    — `ContactRepository` has none, and this MVP's `ConversationId` is
    1:1-per-contact by construction, so conversations are an adequate
    proxy for contacts here.

    A summarization failure for one contact never aborts the batch — same
    "one bad unit must not corrupt the rest of the sweep" posture as the
    other two workers above. Returns how many contacts were compacted.
    """
    conversations = await conversation_repository.list_recent(limit=batch_size)
    compacted_count = 0
    for conversation in conversations:
        contact_id = conversation.contact_id
        existing = await contact_memory_repository.get_by_contact_id(contact_id)
        watermark = existing.last_compacted_message_id if existing is not None else None
        new_messages = await message_repository.get_by_conversation_id_after(
            conversation.id, watermark
        )
        if len(new_messages) < threshold:
            continue

        try:
            await memory_service.compact(contact_id, conversation.id)
            compacted_count += 1
        except Exception:  # noqa: BLE001 - one contact's summarization failure must not break the sweep
            continue

    return compacted_count
