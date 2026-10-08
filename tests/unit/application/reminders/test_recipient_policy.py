import pytest

from app.application.reminders.recipient_policy import ReminderRecipientPolicy
from app.domain.value_objects.phone_number import PhoneNumber

PHONE = PhoneNumber("+5491112345678")
OTHER_PHONE = PhoneNumber("+5491199999999")


@pytest.mark.parametrize(
    ("mode", "allowlist", "phone", "expected"),
    [
        ("allowlist", (), PHONE, False),
        ("allowlist", (str(PHONE),), PHONE, True),
        ("allowlist", (str(PHONE),), OTHER_PHONE, False),
        ("all", (), PHONE, True),
        ("all", (), OTHER_PHONE, True),
    ],
)
def test_recipient_policy_truth_table(mode, allowlist, phone, expected):
    policy = ReminderRecipientPolicy(mode, allowlist)

    assert policy.allows(phone) is expected


def test_recipient_policy_normalizes_allowlist_and_fails_closed_to_start():
    policy = ReminderRecipientPolicy("allowlist", {" +5491112345678 "})

    assert policy.allowlist == frozenset({str(PHONE)})
    assert policy.can_run(enabled=False) is False
    assert policy.can_run(enabled=True) is True
    assert ReminderRecipientPolicy("allowlist", ()).can_run(enabled=True) is False
    assert ReminderRecipientPolicy("all", ()).can_run(enabled=True) is True
