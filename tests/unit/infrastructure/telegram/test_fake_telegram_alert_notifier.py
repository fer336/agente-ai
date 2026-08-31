import pytest

from app.domain.repositories.alert_notifier import AlertNotifier
from app.infrastructure.telegram.fake_telegram_alert_notifier import FakeTelegramAlertNotifier


def test_satisfies_alert_notifier_protocol():
    assert isinstance(FakeTelegramAlertNotifier(), AlertNotifier)


@pytest.mark.asyncio
async def test_notify_records_the_sent_text():
    notifier = FakeTelegramAlertNotifier()

    await notifier.notify("hello")

    assert notifier.sent_messages == ["hello"]
