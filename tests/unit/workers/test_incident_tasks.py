from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.incident import INCIDENT_OPEN
from app.workers.incident_tasks import check_incident_recovery
from tests.fixtures.gateways import (
    make_incident_repository,
    make_linear_gateway,
    make_telegram_notifier,
)
from tests.fixtures.seed_objects import make_incident

_NOW = datetime(2026, 8, 31, 1, 0, tzinfo=UTC)
_QUIET_WINDOW_SECONDS = 600


@pytest.mark.asyncio
async def test_recovers_an_incident_quiet_past_the_window():
    incident_repository = make_incident_repository()
    await incident_repository.save(
        make_incident(id_="inc-1", last_seen=_NOW - timedelta(seconds=700), status=INCIDENT_OPEN)
    )
    telegram_notifier = make_telegram_notifier()
    linear_gateway = make_linear_gateway()

    count = await check_incident_recovery(
        incident_repository, telegram_notifier, linear_gateway, _QUIET_WINDOW_SECONDS, _NOW
    )

    assert count == 1
    assert await incident_repository.list_open() == []
    assert len(telegram_notifier.sent_messages) == 1
    assert "Recuperado" in telegram_notifier.sent_messages[0]


@pytest.mark.asyncio
async def test_leaves_a_still_active_incident_open():
    incident_repository = make_incident_repository()
    await incident_repository.save(
        make_incident(id_="inc-1", last_seen=_NOW - timedelta(seconds=10), status=INCIDENT_OPEN)
    )
    telegram_notifier = make_telegram_notifier()
    linear_gateway = make_linear_gateway()

    count = await check_incident_recovery(
        incident_repository, telegram_notifier, linear_gateway, _QUIET_WINDOW_SECONDS, _NOW
    )

    assert count == 0
    assert telegram_notifier.sent_messages == []
    open_incidents = await incident_repository.list_open()
    assert len(open_incidents) == 1
    assert open_incidents[0].status == INCIDENT_OPEN


@pytest.mark.asyncio
async def test_adds_a_linear_comment_when_the_incident_has_an_issue():
    incident_repository = make_incident_repository()
    await incident_repository.save(
        make_incident(
            id_="inc-1",
            last_seen=_NOW - timedelta(seconds=700),
            status=INCIDENT_OPEN,
            linear_issue_id="CLI-42",
        )
    )
    telegram_notifier = make_telegram_notifier()
    linear_gateway = make_linear_gateway()

    await check_incident_recovery(
        incident_repository, telegram_notifier, linear_gateway, _QUIET_WINDOW_SECONDS, _NOW
    )

    assert linear_gateway.comments == [("CLI-42", linear_gateway.comments[0][1])]


@pytest.mark.asyncio
async def test_never_touches_a_linear_issue_when_none_is_set():
    incident_repository = make_incident_repository()
    await incident_repository.save(
        make_incident(id_="inc-1", last_seen=_NOW - timedelta(seconds=700), status=INCIDENT_OPEN)
    )
    linear_gateway = make_linear_gateway()

    await check_incident_recovery(
        incident_repository, make_telegram_notifier(), linear_gateway, _QUIET_WINDOW_SECONDS, _NOW
    )

    assert linear_gateway.comments == []


class _FailingTelegramNotifier:
    async def notify(self, text: str) -> None:
        raise RuntimeError("telegram down")


@pytest.mark.asyncio
async def test_a_failing_telegram_notification_does_not_abort_the_sweep():
    incident_repository = make_incident_repository()
    await incident_repository.save(
        make_incident(id_="inc-1", last_seen=_NOW - timedelta(seconds=700), status=INCIDENT_OPEN)
    )

    count = await check_incident_recovery(
        incident_repository,
        _FailingTelegramNotifier(),
        make_linear_gateway(),
        _QUIET_WINDOW_SECONDS,
        _NOW,
    )

    assert count == 1
    assert await incident_repository.list_open() == []
