from dataclasses import dataclass
from datetime import datetime


@dataclass
class ContactMemory:
    """One compacted, incrementally-updated summary per contact (conversational-
    memory module — no PRD.md section number, this is this session's own brief).

    NOT a transcript — `summary` is expected to hold only future-useful
    information (name, preferences, gestiones already done, pending info,
    decisions taken), produced by `MemoryService.compact()`. One row per
    contact, overwritten on each compaction (no version history kept here —
    see `MemoryService.compact()`'s own docstring for why).
    """

    id: str
    contact_id: str
    summary: str
    last_compacted_message_id: str | None
    last_compacted_at: datetime | None
    updated_at: datetime
