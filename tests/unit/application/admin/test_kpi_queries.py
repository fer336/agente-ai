from datetime import UTC, date, datetime, timedelta

import pytest

from app.application.admin.kpi_queries import (
    NO_SPECIALTY_LABEL,
    KpiQueryService,
)
from app.infrastructure.database.fake_pending_action_repository import (
    FakePendingActionRepository,
)
from app.infrastructure.database.fake_tool_execution_repository import (
    FakeToolExecutionRepository,
)
from tests.fixtures.gateways import make_agent_run_repository
from tests.fixtures.seed_objects import (
    make_agent_run,
    make_pending_action,
    make_tool_execution,
)

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
# Clinic is UTC-3 all year (Argentina has no DST).
FROM = date(2026, 9, 1)
TO = date(2026, 9, 30)


class Harness:
    def __init__(self, row_cap: int = 20000) -> None:
        self.pending = FakePendingActionRepository()
        self.agent_runs = make_agent_run_repository()
        self.tools = FakeToolExecutionRepository(agent_runs=self.agent_runs)
        self.service = KpiQueryService(
            pending_actions=self.pending,
            tool_executions=self.tools,
            clinic_timezone="America/Argentina/Buenos_Aires",
            row_cap=row_cap,
        )
        self._n = 0

    async def confirm(
        self,
        action_type: str,
        confirmed_at: datetime,
        conversation_id: str = "conv-1",
        payload: dict[str, object] | None = None,
        status: str = "confirmed",
    ) -> str:
        self._n += 1
        id_ = f"pa-{self._n}"
        await self.pending.save(
            make_pending_action(
                id_=id_,
                conversation_id=conversation_id,
                action_type=action_type,
                payload=payload if payload is not None else {},
                status=status,
            )
        )
        self.pending.set_confirmed_at(id_, confirmed_at)
        return id_

    async def evidence(
        self, operation: str, created_at: datetime, conversation_id: str = "conv-1"
    ) -> None:
        self._n += 1
        run_id = f"run-{conversation_id}"
        if await self.agent_runs.get_by_id(run_id) is None:
            await self.agent_runs.save(make_agent_run(id_=run_id, conversation_id=conversation_id))
        await self.tools.save(
            make_tool_execution(
                id_=f"te-{self._n}",
                agent_run_id=run_id,
                tool_name=(
                    "CreateAppointmentTool"
                    if operation == "create_appointment"
                    else "CancelAppointmentTool"
                ),
                operation=operation,
                created_at=created_at,
            )
        )

    async def kpis(self, date_from: date = FROM, date_to: date = TO, **kwargs):
        return await self.service.get_kpis(date_from, date_to, NOW, **kwargs)


def _utc(day: int, hour: int, minute: int = 0, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.asyncio
async def test_empty_period_returns_zeroes_and_zero_filled_series():
    kpis = await Harness().kpis()

    assert kpis.taken == 0 and kpis.cancelled == 0 and kpis.rescheduled == 0
    assert kpis.previous.taken == 0
    assert len(kpis.per_day) == 30
    assert all(day.taken == 0 and day.cancelled == 0 for day in kpis.per_day)
    assert kpis.top_professionals == () and kpis.top_specialties == ()
    assert kpis.weekday == (0,) * 7 and kpis.hour == (0,) * 24
    assert kpis.without_slot == 0
    assert kpis.truncated is False
    assert kpis.generated_at == NOW


@pytest.mark.asyncio
async def test_period_is_echoed_with_clinic_local_bounds_converted_to_utc():
    kpis = await Harness().kpis()

    assert kpis.period.date_from == FROM and kpis.period.date_to == TO
    assert kpis.period.days == 30
    assert kpis.period.start == datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    assert kpis.period.end == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert kpis.previous_period.date_from == date(2026, 8, 2)
    assert kpis.previous_period.date_to == date(2026, 8, 31)


@pytest.mark.asyncio
async def test_counts_taken_cancelled_and_reschedules_separately():
    h = Harness()
    await h.confirm("create_appointment", _utc(5, 15))
    await h.confirm("create_appointment", _utc(6, 15))
    await h.confirm("cancel_appointment", _utc(7, 15))
    await h.confirm("reschedule_appointment", _utc(8, 15))
    await h.confirm("create_appointment", _utc(9, 15), status="expired")
    await h.confirm("something_else", _utc(9, 15))

    kpis = await h.kpis()

    assert (kpis.taken, kpis.cancelled, kpis.rescheduled) == (2, 1, 1)


@pytest.mark.asyncio
async def test_previous_period_of_equal_length_is_counted():
    h = Harness()
    await h.confirm("create_appointment", _utc(10, 15, month=8))  # previous
    await h.confirm("create_appointment", _utc(11, 15, month=8))
    await h.confirm("cancel_appointment", _utc(12, 15, month=8))
    await h.confirm("reschedule_appointment", _utc(13, 15, month=8))
    await h.confirm("create_appointment", _utc(1, 5, month=8))  # before previous: ignored
    await h.confirm("create_appointment", _utc(5, 15))  # current

    kpis = await h.kpis()

    assert kpis.taken == 1
    assert (kpis.previous.taken, kpis.previous.cancelled, kpis.previous.rescheduled) == (2, 1, 1)


@pytest.mark.asyncio
async def test_per_day_series_includes_zero_days_and_uses_clinic_dates():
    h = Harness()
    await h.confirm("create_appointment", _utc(3, 15))
    await h.confirm("create_appointment", _utc(3, 16))
    await h.confirm("cancel_appointment", _utc(5, 15))

    kpis = await h.kpis(date(2026, 9, 3), date(2026, 9, 6))

    assert [(d.date, d.taken, d.cancelled) for d in kpis.per_day] == [
        (date(2026, 9, 3), 2, 0),
        (date(2026, 9, 4), 0, 0),
        (date(2026, 9, 5), 0, 1),
        (date(2026, 9, 6), 0, 0),
    ]


@pytest.mark.asyncio
async def test_clinic_timezone_day_boundary_0230_utc_belongs_to_previous_clinic_day():
    h = Harness()
    # 02:30 UTC on Sep 4 is 23:30 on Sep 3 in Buenos Aires.
    await h.confirm("create_appointment", _utc(4, 2, 30))
    # 03:00 UTC on Sep 4 is 00:00 on Sep 4 (first instant of the day).
    await h.confirm("create_appointment", _utc(4, 3, 0))

    kpis = await h.kpis(date(2026, 9, 3), date(2026, 9, 4))

    assert [(d.date, d.taken) for d in kpis.per_day] == [
        (date(2026, 9, 3), 1),
        (date(2026, 9, 4), 1),
    ]


@pytest.mark.asyncio
async def test_period_bounds_are_clinic_local_end_exclusive():
    h = Harness()
    await h.confirm("create_appointment", _utc(1, 2, 59))  # Aug 31 23:59 local: previous
    await h.confirm("create_appointment", _utc(1, 3, 0))  # Sep 1 00:00 local: in
    await h.confirm("create_appointment", _utc(1, 2, 59, month=10))  # Sep 30 23:59 local: in
    await h.confirm("create_appointment", _utc(1, 3, 0, month=10))  # Oct 1 00:00 local: out

    kpis = await h.kpis()

    assert kpis.taken == 2
    assert kpis.previous.taken == 1


@pytest.mark.asyncio
async def test_top_professionals_and_specialties_with_missing_specialty_grouped():
    h = Harness()
    payloads = [
        {"professional_id": "7", "specialty_id": "10"},
        {"professional_id": "7", "specialty_id": "10"},
        {"professional_id": "7", "specialty_id": ""},
        {"professional_id": "8"},
        {"professional_id": 9, "specialty_id": "11"},
    ]
    for i, payload in enumerate(payloads):
        await h.confirm("create_appointment", _utc(5, 12 + i), payload=payload)
    # A cancellation must not feed the "most booked" lists.
    await h.confirm(
        "cancel_appointment", _utc(6, 12), payload={"professional_id": "8", "specialty_id": "11"}
    )

    kpis = await h.kpis()

    assert [(t.id, t.count) for t in kpis.top_professionals] == [("7", 3), ("8", 1), ("9", 1)]
    # Empty and missing specialty collapse into one group, listed first on the tie (id asc).
    assert [(t.id, t.label, t.count) for t in kpis.top_specialties] == [
        ("", NO_SPECIALTY_LABEL, 2),
        ("10", "10", 2),
        ("11", "11", 1),
    ]


@pytest.mark.asyncio
async def test_name_resolver_labels_with_id_fallback():
    h = Harness()
    await h.confirm(
        "create_appointment", _utc(5, 12), payload={"professional_id": "7", "specialty_id": "10"}
    )
    await h.confirm(
        "create_appointment", _utc(5, 13), payload={"professional_id": "8", "specialty_id": "10"}
    )

    kpis = await h.kpis(
        professional_names=lambda id_: {"7": "Dra. Perez"}.get(id_),
        specialty_names=lambda id_: None,
    )

    assert {t.id: t.label for t in kpis.top_professionals} == {"7": "Dra. Perez", "8": "8"}
    assert kpis.top_specialties[0].label == "10"


@pytest.mark.asyncio
async def test_weekday_and_hour_use_clinic_time_and_missing_slot_start_is_counted():
    h = Harness()
    # 2026-09-07 is a Monday. 02:00 UTC Tuesday 09-08 slot = Monday 23:00 local.
    await h.confirm(
        "create_appointment", _utc(1, 15), payload={"slot_start": "2026-09-08T02:00:00+00:00"}
    )
    # Naive slot_start is treated as clinic wall-clock: Wednesday 10:30.
    await h.confirm(
        "create_appointment", _utc(1, 16), payload={"slot_start": "2026-09-09T10:30:00"}
    )
    # Aware slot in clinic offset: Sunday 08:00.
    await h.confirm(
        "create_appointment", _utc(1, 17), payload={"slot_start": "2026-09-13T08:00:00-03:00"}
    )
    await h.confirm("create_appointment", _utc(1, 18), payload={})
    await h.confirm("create_appointment", _utc(1, 19), payload={"slot_start": "not a date"})
    await h.confirm("create_appointment", _utc(1, 20), payload={"slot_start": 12345})

    kpis = await h.kpis()

    assert kpis.taken == 6
    assert kpis.without_slot == 3
    assert kpis.weekday == (1, 0, 1, 0, 0, 0, 1)
    assert kpis.hour[23] == 1 and kpis.hour[10] == 1 and kpis.hour[8] == 1
    assert sum(kpis.hour) == 3


@pytest.mark.asyncio
async def test_evidence_matches_same_conversation_within_window_one_to_one():
    h = Harness()
    t1 = _utc(5, 15)
    await h.confirm("create_appointment", t1)  # evidence 1 min after: with
    await h.evidence("create_appointment", t1 + timedelta(minutes=1))
    t2 = _utc(6, 15)
    await h.confirm("create_appointment", t2)  # evidence 11 min after: without
    await h.evidence("create_appointment", t2 + timedelta(minutes=11))
    t3 = _utc(7, 15)
    await h.confirm("create_appointment", t3, conversation_id="conv-2")  # other conversation
    await h.evidence("create_appointment", t3)
    t4 = _utc(8, 15)
    await h.confirm("create_appointment", t4)  # 2 min before: with (edge)
    await h.evidence("create_appointment", t4 - timedelta(minutes=2))
    t5 = _utc(9, 15)
    await h.confirm("create_appointment", t5)  # two rows, one execution: only one matches
    await h.confirm("create_appointment", t5 + timedelta(minutes=1))
    await h.evidence("create_appointment", t5)
    t6 = _utc(10, 15)
    await h.confirm("cancel_appointment", t6)  # cancel evidence
    await h.evidence("cancel_appointment", t6 + timedelta(minutes=2))
    await h.confirm("cancel_appointment", _utc(11, 15))  # none
    # A create execution never backs a cancellation.
    await h.evidence("create_appointment", _utc(11, 15))

    kpis = await h.kpis()

    assert kpis.taken == 6
    assert (kpis.evidence.taken_with, kpis.evidence.taken_without) == (3, 3)
    assert (kpis.evidence.cancelled_with, kpis.evidence.cancelled_without) == (1, 1)
    assert kpis.evidence.truncated is False


@pytest.mark.asyncio
async def test_truncation_is_exact_at_the_cap_and_aggregates_only_row_cap():
    h = Harness(row_cap=3)
    for i in range(3):
        await h.confirm("create_appointment", _utc(5, 10 + i))

    exact = await h.kpis()
    assert exact.taken == 3 and exact.truncated is False

    await h.confirm("create_appointment", _utc(5, 20))  # fourth row, newest

    over = await h.kpis()
    assert over.taken == 3 and over.truncated is True


@pytest.mark.asyncio
async def test_row_cap_is_clamped_to_hard_maximum():
    with pytest.raises(ValueError):
        KpiQueryService(
            pending_actions=FakePendingActionRepository(),
            tool_executions=FakeToolExecutionRepository(),
            row_cap=20001,
        )


@pytest.mark.asyncio
async def test_invalid_ranges_raise_value_error():
    h = Harness()
    with pytest.raises(ValueError, match="after"):
        await h.kpis(date(2026, 9, 10), date(2026, 9, 9))
    with pytest.raises(ValueError, match="366"):
        await h.kpis(date(2025, 1, 1), date(2026, 1, 2))  # 367 days


@pytest.mark.asyncio
async def test_range_of_366_days_is_allowed_and_single_day_is_allowed():
    h = Harness()
    year = await h.kpis(date(2025, 1, 1), date(2025, 12, 31))
    leap = await h.kpis(date(2024, 1, 1), date(2024, 12, 31))
    one = await h.kpis(date(2026, 9, 1), date(2026, 9, 1))

    assert year.period.days == 365 and leap.period.days == 366
    assert len(one.per_day) == 1
