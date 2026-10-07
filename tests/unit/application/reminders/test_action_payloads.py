import pytest

from app.application.reminders.action_payloads import ReminderActionKind, parse_reminder_action


@pytest.mark.parametrize(
    ("payload", "kind", "appointment_id"),
    [
        ("REMINDER_CONFIRM:appointment-1", ReminderActionKind.CONFIRM, "appointment-1"),
        ("REMINDER_CANCEL:appointment-1", ReminderActionKind.CANCEL, "appointment-1"),
        (
            "REMINDER_CANCEL_CONFIRM:appointment-1",
            ReminderActionKind.CANCEL_CONFIRM,
            "appointment-1",
        ),
        ("REMINDER_CANCEL_KEEP:appointment-1", ReminderActionKind.CANCEL_KEEP, "appointment-1"),
        ("REMINDER_LOCATION:appointment-1", ReminderActionKind.LOCATION, "appointment-1"),
        ("REMINDER_RESCHEDULE:appointment-1", ReminderActionKind.RESCHEDULE, "appointment-1"),
        ("REMINDER_REVIEW_OPTOUT", ReminderActionKind.REVIEW_OPTOUT, None),
    ],
)
def test_parse_reminder_action_accepts_only_known_machine_payloads(payload, kind, appointment_id):
    action = parse_reminder_action(payload)

    assert action is not None
    assert action.kind is kind
    assert action.appointment_id == appointment_id


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "REMINDER_CONFIRM:",
        "REMINDER_CONFIRM:a:b",
        "REMINDER_RESCHEDULE:",
        "REMINDER_RESCHEDULE:a:b",
        "REMINDER_REVIEW_OPTOUT:x",
        "MENU_MAIN",
    ],
)
def test_parse_reminder_action_rejects_malformed_or_unknown_payloads(payload):
    assert parse_reminder_action(payload) is None
