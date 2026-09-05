from datetime import UTC, datetime

from app.domain.entities.contact_memory import ContactMemory


def test_creates_contact_memory_with_all_fields():
    now = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    memory = ContactMemory(
        id="mem-1",
        contact_id="contact-1",
        summary="Juan Perez, prefiere turnos por la tarde",
        last_compacted_message_id="msg-10",
        last_compacted_at=now,
        updated_at=now,
    )

    assert memory.contact_id == "contact-1"
    assert memory.summary == "Juan Perez, prefiere turnos por la tarde"
    assert memory.last_compacted_message_id == "msg-10"
    assert memory.last_compacted_at == now


def test_allows_no_prior_compaction():
    memory = ContactMemory(
        id="mem-2",
        contact_id="contact-2",
        summary="",
        last_compacted_message_id=None,
        last_compacted_at=None,
        updated_at=datetime(2026, 8, 31, 9, 0, tzinfo=UTC),
    )

    assert memory.summary == ""
    assert memory.last_compacted_message_id is None
    assert memory.last_compacted_at is None
