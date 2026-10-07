from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.entities.appointment_reminder import AppointmentReminder
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.database.models.appointment_reminder import AppointmentReminderModel
from app.infrastructure.database.repositories.appointment_reminder_repository import (
    SqlAlchemyAppointmentReminderRepository,
)


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)

    def first(self):
        return self._values[0] if self._values else None


class _Result:
    def __init__(
        self, *, rowcount: int = 0, scalar: object = None, scalars: list[object] | None = None
    ) -> None:
        self.rowcount = rowcount
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar(self):
        return self._scalar

    def scalars(self):
        return _Scalars(self._scalars)


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


@pytest.mark.asyncio
async def test_find_sent_for_inbound_action_returns_the_matching_terminal_reminder():
    sent_at = datetime(2026, 10, 2, 13, tzinfo=UTC)
    model = AppointmentReminderModel(
        id="reminder-1",
        appointment_id="appointment-1",
        patient_id="patient-1",
        kind="confirm_day_before",
        status="sent",
        due_at=sent_at,
        attempts=1,
        recipient_phone="+5491112345678",
        sent_at=sent_at,
    )
    session = AsyncMock()
    session.execute.return_value = _Result(scalars=[model])
    repository = SqlAlchemyAppointmentReminderRepository(session)

    found = await repository.find_sent_for_inbound_action(
        "appointment-1",
        PhoneNumber("+5491112345678"),
        frozenset({"confirm_day_before"}),
    )

    assert found is not None
    assert found.id == "reminder-1"


@pytest.mark.asyncio
async def test_find_sent_for_inbound_action_fails_closed_when_no_match_exists():
    session = AsyncMock()
    session.execute.return_value = _Result()
    repository = SqlAlchemyAppointmentReminderRepository(session)

    found = await repository.find_sent_for_inbound_action(
        "appointment-1",
        PhoneNumber("+5491112345678"),
        frozenset({"confirm_day_before"}),
    )

    assert found is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rejection",
    ["non_sent_status", "different_phone", "different_appointment", "disallowed_kind"],
)
async def test_find_sent_for_inbound_action_rejects_rows_outside_its_authorization_scope(
    rejection: str,
):
    session = AsyncMock()
    session.execute.return_value = _Result()
    repository = SqlAlchemyAppointmentReminderRepository(session)

    await repository.find_sent_for_inbound_action(
        "appointment-1",
        PhoneNumber("+5491112345678"),
        frozenset({"confirm_day_before", "confirm_or_location_same_day"}),
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    expected_predicates = {
        "non_sent_status": "appointment_reminders.status = %(status_1)s",
        "different_phone": "appointment_reminders.recipient_phone = %(recipient_phone_1)s",
        "different_appointment": "appointment_reminders.appointment_id = %(appointment_id_1)s",
        "disallowed_kind": "appointment_reminders.kind IN",
    }
    assert expected_predicates[rejection] in sql
    assert "sent" in compiled.params.values()
    assert "appointment-1" in compiled.params.values()
    assert "+5491112345678" in compiled.params.values()
    assert any(
        set(value) == {"confirm_day_before", "confirm_or_location_same_day"}
        for value in compiled.params.values()
        if isinstance(value, (tuple, list, frozenset))
    )


@pytest.mark.asyncio
async def test_find_sent_for_inbound_action_fails_closed_for_no_allowed_kinds():
    session = AsyncMock()
    repository = SqlAlchemyAppointmentReminderRepository(session)

    found = await repository.find_sent_for_inbound_action(
        "appointment-1", PhoneNumber("+5491112345678"), frozenset()
    )

    assert found is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_has_sent_review_request_for_recipient_requires_a_terminal_review_request_for_phone():
    session = AsyncMock()
    session.execute.return_value = _Result(scalar=True)
    repository = SqlAlchemyAppointmentReminderRepository(session)

    assert await repository.has_sent_review_request_for_recipient(PhoneNumber("+5491112345678"))

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "appointment_reminders.recipient_phone = %(recipient_phone_1)s" in sql
    assert "appointment_reminders.kind = %(kind_1)s" in sql
    assert "appointment_reminders.status = %(status_1)s" in sql
    assert {"+5491112345678", "review_request", "sent"}.issubset(compiled.params.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, None])
async def test_has_sent_review_request_for_recipient_fails_closed_without_an_authorized_row(result):
    session = AsyncMock()
    session.execute.return_value = _Result(scalar=result)
    repository = SqlAlchemyAppointmentReminderRepository(session)

    assert (
        await repository.has_sent_review_request_for_recipient(PhoneNumber("+5491112345678"))
    ) is False


@pytest.mark.asyncio
async def test_upsert_persists_and_refreshes_the_appointment_start(reminder: AppointmentReminder):
    starts_at = datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    reminder.appointment_starts_at = starts_at
    session = AsyncMock()
    session.execute.return_value = _Result(rowcount=1)

    await SqlAlchemyAppointmentReminderRepository(session).upsert(reminder)

    compiled = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert starts_at in compiled.params.values()
    assert "appointment_starts_at=excluded.appointment_starts_at" in str(compiled).replace(
        " ", ""
    ) or "appointment_starts_at = excluded.appointment_starts_at" in str(compiled)


@pytest.mark.asyncio
async def test_find_latest_sent_pending_reminder_filters_kind_window_and_future_start():
    session = AsyncMock()
    row = AppointmentReminderModel(
        id="reminder-1",
        appointment_id="appointment-1",
        patient_id="patient-1",
        kind="confirm_day_before",
        status="sent",
        due_at=datetime(2026, 10, 7, 21, tzinfo=UTC),
        recipient_phone="+5491112345678",
        attempts=1,
        appointment_starts_at=datetime(2026, 10, 8, 13, 30, tzinfo=UTC),
    )
    session.execute.return_value = _Result(scalars=[row])
    sent_since = datetime(2026, 10, 5, 12, tzinfo=UTC)
    now = datetime(2026, 10, 7, 12, tzinfo=UTC)

    found = await SqlAlchemyAppointmentReminderRepository(
        session
    ).find_latest_sent_pending_appointment_reminder(
        PhoneNumber("+5491112345678"), sent_since=sent_since, now=now
    )

    assert found is not None and found.id == "reminder-1"
    assert found.appointment_starts_at == row.appointment_starts_at
    compiled = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "appointment_reminders.recipient_phone = %(recipient_phone_1)s" in sql
    assert "appointment_reminders.status = %(status_1)s" in sql
    assert "appointment_reminders.kind IN" in sql
    assert "appointment_reminders.sent_at >= %(sent_at_1)s" in sql
    assert "appointment_reminders.appointment_starts_at > %(appointment_starts_at_1)s" in sql
    assert "ORDER BY appointment_reminders.sent_at DESC" in sql
    assert "LIMIT" in sql
    values = compiled.params.values()
    for expected in ("+5491112345678", "sent", sent_since, now):
        assert expected in values
    assert any(
        set(value) == {"confirm_day_before", "confirm_or_location_same_day"}
        for value in values
        if isinstance(value, (tuple, list, frozenset))
    )


@pytest.mark.asyncio
async def test_find_latest_sent_pending_reminder_returns_none_without_a_match():
    session = AsyncMock()
    session.execute.return_value = _Result(scalars=[])

    found = await SqlAlchemyAppointmentReminderRepository(
        session
    ).find_latest_sent_pending_appointment_reminder(
        PhoneNumber("+5491112345678"),
        sent_since=datetime(2026, 10, 5, tzinfo=UTC),
        now=datetime(2026, 10, 7, tzinfo=UTC),
    )

    assert found is None


@pytest.mark.asyncio
async def test_latest_pending_appointment_start_selects_the_max_future_start_of_sent_reminders():
    session = AsyncMock()
    expected = datetime(2026, 10, 8, 13, 30, tzinfo=UTC)
    session.execute.return_value = _Result(scalar=expected)
    now = datetime(2026, 10, 7, 12, tzinfo=UTC)

    found = await SqlAlchemyAppointmentReminderRepository(session).latest_pending_appointment_start(
        PhoneNumber("+5491112345678"), now=now
    )

    assert found == expected
    compiled = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "max(appointment_reminders.appointment_starts_at)" in sql
    assert "appointment_reminders.recipient_phone = %(recipient_phone_1)s" in sql
    assert "appointment_reminders.status = %(status_1)s" in sql
    assert "appointment_reminders.kind IN" in sql
    assert "appointment_reminders.appointment_starts_at > %(appointment_starts_at_1)s" in sql
    assert "appointment_reminders.sent_at" not in sql
    for expected_value in ("+5491112345678", "sent", now):
        assert expected_value in compiled.params.values()


@pytest.mark.asyncio
async def test_latest_pending_appointment_start_is_none_without_a_match():
    session = AsyncMock()
    session.execute.return_value = _Result(scalar=None)

    assert (
        await SqlAlchemyAppointmentReminderRepository(session).latest_pending_appointment_start(
            PhoneNumber("+5491112345678"), now=datetime(2026, 10, 7, tzinfo=UTC)
        )
        is None
    )
