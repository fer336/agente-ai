from app.domain.entities.human_handoff import HumanHandoff
from app.domain.value_objects.conversation_id import ConversationId


def test_creates_human_handoff_with_all_fields():
    handoff = HumanHandoff(
        id="hh-1",
        conversation_id=ConversationId(value="conv-1"),
        reason="ambiguous_confirmation",
        status="requested",
    )

    assert handoff.reason == "ambiguous_confirmation"
    assert handoff.status == "requested"


def test_human_handoffs_with_different_status_are_not_equal():
    first = HumanHandoff(
        id="hh-2",
        conversation_id=ConversationId(value="conv-2"),
        reason="urgency",
        status="requested",
    )
    second = HumanHandoff(
        id="hh-2",
        conversation_id=ConversationId(value="conv-2"),
        reason="urgency",
        status="resolved",
    )

    assert first != second
