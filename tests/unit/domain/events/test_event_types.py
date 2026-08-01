from app.domain.events import event_types


def test_event_type_constants_match_outbox_pattern_section():
    assert event_types.APPOINTMENT_CREATED == "appointment.created"
    assert event_types.APPOINTMENT_RESCHEDULED == "appointment.rescheduled"
    assert event_types.APPOINTMENT_CANCELLED == "appointment.cancelled"
    assert event_types.MESSAGE_REPLY_REQUESTED == "message.reply_requested"
    assert event_types.HUMAN_HANDOFF_REQUESTED == "human_handoff.requested"
    assert event_types.REMINDER_REQUESTED == "reminder.requested"
