from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.infrastructure.database.repositories.appointment_reminder_repository import (
    SqlAlchemyAppointmentReminderRepository,
)


class _Result:
    def __init__(self, *, rowcount: int = 0, scalar: object = None) -> None:
        self.rowcount = rowcount
        self._scalar = scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return []


@pytest.fixture
def reminder() -> AppointmentReminder:
    return AppointmentReminder(
        id="reminder-1",
        appointment_id="appointment-1",
        patient_id="patient-1",
        kind="review_request",
        status="pending",
        due_at=datetime(2026, 10, 2, 13, tzinfo=UTC),
        recipient_phone="+5491112345678",
    )


@pytest.mark.asyncio
async def test_upsert_only_refreshes_pending_or_failed_rows(reminder: AppointmentReminder):
    session = AsyncMock()
    session.execute.return_value = _Result(rowcount=0)
    repository = SqlAlchemyAppointmentReminderRepository(session)

    inserted = await repository.upsert(reminder)

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert inserted is False
    assert "ON CONFLICT (appointment_id, kind) DO UPDATE" in sql
    assert "appointment_reminders.status IN" in sql
    assert ["pending", "failed"] in compiled.params.values()
    assert "CASE WHEN (appointment_reminders.status = %(status_1)s AND " in sql
    assert "appointment_reminders.attempts > %(attempts_1)s) " in sql
    assert "THEN appointment_reminders.due_at ELSE excluded.due_at END" in sql


@pytest.mark.asyncio
async def test_upsert_never_resets_a_processing_row_during_delivery(
    reminder: AppointmentReminder,
):
    session = AsyncMock()
    session.execute.return_value = _Result(rowcount=0)
    repository = SqlAlchemyAppointmentReminderRepository(session)

    updated = await repository.upsert(reminder)

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert updated is False
    assert "appointment_reminders.status IN" in sql
    assert ["pending", "failed"] in compiled.params.values()


@pytest.mark.asyncio
async def test_list_due_selects_only_pending_rows_due_by_the_current_instant():
    session = AsyncMock()
    session.execute.return_value = _Result()
    repository = SqlAlchemyAppointmentReminderRepository(session)

    assert await repository.list_due(datetime(2026, 10, 2, 13, tzinfo=UTC), limit=50) == []

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "appointment_reminders.status = %(status_1)s" in sql
    assert "appointment_reminders.due_at <= %(due_at_1)s" in sql


@pytest.mark.asyncio
async def test_claim_uses_pending_status_and_claim_timestamp_as_its_cas_guard():
    session = AsyncMock()
    session.execute.return_value = _Result(rowcount=1)
    repository = SqlAlchemyAppointmentReminderRepository(session)
    claimed_at = datetime(2026, 10, 2, 13, tzinfo=UTC)

    won = await repository.claim("reminder-1", claimed_at)

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert won is True
    assert (
        "WHERE appointment_reminders.id = %(id_1)s AND appointment_reminders.status = %(status_1)s"
    ) in sql
    assert "attempts=(appointment_reminders.attempts + %(attempts_1)s)" in sql


@pytest.mark.asyncio
async def test_reclaim_and_skip_are_bounded_by_processing_claim_state():
    session = AsyncMock()
    session.execute.side_effect = [_Result(rowcount=1), _Result(rowcount=1)]
    repository = SqlAlchemyAppointmentReminderRepository(session)
    claimed_at = datetime(2026, 10, 2, 13, tzinfo=UTC)

    assert await repository.reclaim_stale_claims(claimed_at) == 1
    assert (
        await repository.mark_skipped(
            "reminder-1", claimed_at=claimed_at, reason="stale", skipped_at=claimed_at
        )
        is True
    )

    reclaim_sql = str(
        session.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect())
    )
    skip_sql = str(session.execute.await_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert "appointment_reminders.status = %(status_1)s" in reclaim_sql
    assert "appointment_reminders.claimed_at < %(claimed_at_1)s" in reclaim_sql
    assert "appointment_reminders.claimed_at = %(claimed_at_1)s" in skip_sql
    assert "status=%(status)s" in skip_sql


@pytest.mark.asyncio
async def test_skip_pending_and_renew_claim_use_compare_and_swap_guards():
    session = AsyncMock()
    session.execute.side_effect = [_Result(rowcount=1), _Result(rowcount=1)]
    repository = SqlAlchemyAppointmentReminderRepository(session)
    claimed_at = datetime(2026, 10, 2, 13, tzinfo=UTC)
    renewed_at = claimed_at + timedelta(seconds=1)

    assert await repository.skip_pending("reminder-1", reason="allowlist", skipped_at=claimed_at)
    assert await repository.renew_claim("reminder-1", claimed_at=claimed_at, renewed_at=renewed_at)

    skip_sql = str(session.execute.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    renew_sql = str(
        session.execute.await_args_list[1].args[0].compile(dialect=postgresql.dialect())
    )
    assert "appointment_reminders.status = %(status_1)s" in skip_sql
    assert "appointment_reminders.claimed_at = %(claimed_at_1)s" in renew_sql
    assert "claimed_at=%(claimed_at)s" in renew_sql


@pytest.mark.asyncio
async def test_release_or_fail_and_mark_sent_require_the_same_claim_timestamp():
    session = AsyncMock()
    session.execute.side_effect = [_Result(rowcount=1), _Result(rowcount=0)]
    repository = SqlAlchemyAppointmentReminderRepository(session)
    claimed_at = datetime(2026, 10, 2, 13, tzinfo=UTC)

    released = await repository.release_or_fail(
        "reminder-1",
        claimed_at=claimed_at,
        error="temporary provider error",
        retry_at=datetime(2026, 10, 2, 13, 5, tzinfo=UTC),
    )
    marked_sent = await repository.mark_sent(
        "reminder-1",
        claimed_at=claimed_at,
        external_message_id="message-1",
        sent_at=datetime(2026, 10, 2, 13, 1, tzinfo=UTC),
    )

    release_statement = session.execute.await_args_list[0].args[0]
    sent_statement = session.execute.await_args_list[1].args[0]
    release_sql = str(release_statement.compile(dialect=postgresql.dialect()))
    sent_sql = str(sent_statement.compile(dialect=postgresql.dialect()))
    assert released is True
    assert marked_sent is False
    assert "claimed_at = %(claimed_at_1)s" in release_sql
    assert "claimed_at = %(claimed_at_1)s" in sent_sql


@pytest.mark.asyncio
async def test_has_sent_review_request_since_scopes_to_patient_kind_status_and_cutoff():
    session = AsyncMock()
    session.execute.return_value = _Result(scalar=True)
    repository = SqlAlchemyAppointmentReminderRepository(session)
    cutoff = datetime.now(UTC) - timedelta(days=90)

    assert await repository.has_sent_review_request_since("patient-1", cutoff) is True

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "appointment_reminders.patient_id = %(patient_id_1)s" in sql
    assert "appointment_reminders.kind = %(kind_1)s" in sql
    assert "appointment_reminders.status = %(status_1)s" in sql
    assert "appointment_reminders.sent_at >= %(sent_at_1)s" in sql
