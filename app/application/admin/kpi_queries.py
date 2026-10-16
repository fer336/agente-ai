from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config.settings import get_settings
from app.domain.repositories.pending_action_repository import (
    ConfirmedActionReader,
    ConfirmedPendingAction,
)
from app.domain.repositories.tool_execution_repository import (
    ToolExecutionEvidence,
    ToolExecutionRepository,
)

# ---------------------------------------------------------------------------
# Counting rules. Everything below is derived from the code, NOT validated
# against production data (the bot had none when this was written; see
# odd/tasks/admin-agent-diagram-and-kpis.md, B1). Change them here.
#
# 1. A "booking" is a `pending_actions` row with `status == 'confirmed'`, dated by
#    `confirmed_at` (stamped by `mark_confirmed_if_pending`; rows confirmed before
#    that stamp existed have NULL and are invisible to these KPIs).
# 2. `confirmed` is NOT proof that Dentalink booked: the status flips before the
#    Dentalink call. Success evidence is a completed `tool_executions` row, which
#    is cross-checked and reported separately (`KpiEvidence`), never used to
#    filter the headline numbers.
# 3. Cancellations are "via bot" only: staff cancellations done directly in
#    Dentalink leave no trace in the bot's DB.
# 4. Reschedules are reported on their own and never added to `taken`.
# 5. Test and real conversations cannot be told apart.
# ---------------------------------------------------------------------------
ACTION_CREATE = "create_appointment"
ACTION_CANCEL = "cancel_appointment"
ACTION_RESCHEDULE = "reschedule_appointment"
KPI_ACTION_TYPES = (ACTION_CREATE, ACTION_CANCEL, ACTION_RESCHEDULE)

#: Real `tool_executions` strings, from `DentalinkAppointmentGateway`
#: (`traced_tool_call(tool_name=..., operation=...)`). Matched on both fields.
EVIDENCE_TOOLS: dict[str, tuple[str, str]] = {
    ACTION_CREATE: ("CreateAppointmentTool", "create_appointment"),
    ACTION_CANCEL: ("CancelAppointmentTool", "cancel_appointment"),
}

#: A tool execution backs a confirmation when it is in the same conversation and was
#: created within [confirmed_at - BEFORE, confirmed_at + AFTER]. The tool runs after the
#: status flip, hence the larger margin after; BEFORE only absorbs clock skew.
EVIDENCE_BEFORE = timedelta(minutes=2)
EVIDENCE_AFTER = timedelta(minutes=10)

#: Payload keys written by `_proposal_payload` (`app/agent/nodes/appointment.py`).
PAYLOAD_PROFESSIONAL = "professional_id"
PAYLOAD_SPECIALTY = "specialty_id"
PAYLOAD_SLOT_START = "slot_start"

NO_SPECIALTY_LABEL = "Sin especialidad"
TOP_N = 10
MAX_DAYS = 366
#: Hard ceiling on rows aggregated per period; `truncated` reports when it was hit.
MAX_ROW_CAP = 20000

NameResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class KpiPeriod:
    """A clinic-local date range and its UTC instants (end exclusive)."""

    date_from: date
    date_to: date
    days: int
    start: datetime
    end: datetime


@dataclass(frozen=True)
class PeriodTotals:
    taken: int
    cancelled: int
    rescheduled: int


@dataclass(frozen=True)
class DailyCount:
    date: date
    taken: int
    cancelled: int


@dataclass(frozen=True)
class TopEntry:
    id: str
    label: str
    count: int


@dataclass(frozen=True)
class KpiEvidence:
    """How many confirmed rows have a matching completed tool execution."""

    taken_with: int
    taken_without: int
    cancelled_with: int
    cancelled_without: int
    #: Unmatched rows whose match window reaches back past the oldest fetched execution,
    #: so a dropped (older) execution might have backed them. Not counted as "without".
    taken_unverifiable: int
    cancelled_unverifiable: int
    truncated: bool  # the evidence fetch hit the row cap
    exact: bool  # the with/without split is complete (False when truncated)


@dataclass(frozen=True)
class Kpis:
    generated_at: datetime
    period: KpiPeriod
    previous_period: KpiPeriod
    taken: int
    cancelled: int  # via bot only
    rescheduled: int
    previous: PeriodTotals
    per_day: tuple[DailyCount, ...]
    top_professionals: tuple[TopEntry, ...]
    top_specialties: tuple[TopEntry, ...]
    weekday: tuple[int, ...]  # 7 entries, 0 = Monday, from taken rows
    hour: tuple[int, ...]  # 24 entries, clinic hour of day, from taken rows
    weekday_hour: tuple[tuple[int, ...], ...]  # 7 rows (0 = Monday) x 24 hours, taken rows
    without_slot: int  # taken rows with missing/unparsable slot_start
    evidence: KpiEvidence
    truncated: bool  # current period hit row_cap
    previous_truncated: bool


class KpiQueryService:
    """Read-only KPI aggregation backing `/admin/api/kpis` (aggregation in Python)."""

    def __init__(
        self,
        pending_actions: ConfirmedActionReader,
        tool_executions: ToolExecutionRepository,
        clinic_timezone: str | None = None,
        row_cap: int = MAX_ROW_CAP,
    ) -> None:
        if not 1 <= row_cap <= MAX_ROW_CAP:
            raise ValueError(f"row_cap must be between 1 and {MAX_ROW_CAP}")
        self._pending_actions = pending_actions
        self._tool_executions = tool_executions
        self._tz = ZoneInfo(
            clinic_timezone if clinic_timezone is not None else get_settings().clinic_timezone
        )
        self._row_cap = row_cap

    async def get_kpis(
        self,
        date_from: date,
        date_to: date,
        now: datetime,
        professional_names: NameResolver | None = None,
        specialty_names: NameResolver | None = None,
    ) -> Kpis:
        """Raises `ValueError` on an invalid range (the endpoint maps it to 422)."""
        if date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        days = (date_to - date_from).days + 1
        if days > MAX_DAYS:
            raise ValueError(f"range must not exceed {MAX_DAYS} days")

        period = self._period(date_from, date_to)
        previous_period = self._period(
            date_from - timedelta(days=days), date_from - timedelta(days=1)
        )

        rows, truncated = await self._fetch(period)
        previous_rows, previous_truncated = await self._fetch(previous_period)

        taken_rows = [r for r in rows if r.action_type == ACTION_CREATE]
        cancelled_rows = [r for r in rows if r.action_type == ACTION_CANCEL]

        weekday, hour, weekday_hour, without_slot = self._slot_distributions(taken_rows)
        return Kpis(
            generated_at=now,
            period=period,
            previous_period=previous_period,
            taken=len(taken_rows),
            cancelled=len(cancelled_rows),
            rescheduled=sum(1 for r in rows if r.action_type == ACTION_RESCHEDULE),
            previous=_totals(previous_rows),
            per_day=self._per_day(period, taken_rows, cancelled_rows),
            top_professionals=_top(
                (_payload_id(r.payload, PAYLOAD_PROFESSIONAL) for r in taken_rows),
                professional_names,
                skip_empty=True,
            ),
            top_specialties=_top(
                (_payload_id(r.payload, PAYLOAD_SPECIALTY) for r in taken_rows),
                specialty_names,
                skip_empty=False,
            ),
            weekday=weekday,
            hour=hour,
            weekday_hour=weekday_hour,
            without_slot=without_slot,
            evidence=await self._evidence(period, taken_rows, cancelled_rows),
            truncated=truncated,
            previous_truncated=previous_truncated,
        )

    def _period(self, date_from: date, date_to: date) -> KpiPeriod:
        start = datetime.combine(date_from, time.min, tzinfo=self._tz).astimezone(UTC)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=self._tz).astimezone(
            UTC
        )
        return KpiPeriod(
            date_from=date_from,
            date_to=date_to,
            days=(date_to - date_from).days + 1,
            start=start,
            end=end,
        )

    async def _fetch(self, period: KpiPeriod) -> tuple[list[ConfirmedPendingAction], bool]:
        # Fetch one extra row so `truncated` is exact (a period with exactly row_cap rows
        # is NOT truncated). Newest first, so the oldest rows are the ones dropped.
        rows = await self._pending_actions.list_confirmed_between(
            KPI_ACTION_TYPES, period.start, period.end, self._row_cap + 1
        )
        return rows[: self._row_cap], len(rows) > self._row_cap

    def _per_day(
        self,
        period: KpiPeriod,
        taken_rows: list[ConfirmedPendingAction],
        cancelled_rows: list[ConfirmedPendingAction],
    ) -> tuple[DailyCount, ...]:
        taken = Counter(self._local_date(r.confirmed_at) for r in taken_rows)
        cancelled = Counter(self._local_date(r.confirmed_at) for r in cancelled_rows)
        days = (period.date_from + timedelta(days=i) for i in range(period.days))
        return tuple(DailyCount(d, taken[d], cancelled[d]) for d in days)

    def _local_date(self, instant: datetime) -> date:
        return instant.astimezone(self._tz).date()

    def _slot_distributions(
        self, taken_rows: list[ConfirmedPendingAction]
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[tuple[int, ...], ...], int]:
        # The marginals are derived from the matrix so they cannot drift apart.
        matrix = [[0] * 24 for _ in range(7)]
        without_slot = 0
        for row in taken_rows:
            slot = self._parse_slot_start(row.payload.get(PAYLOAD_SLOT_START))
            if slot is None:
                without_slot += 1
                continue
            matrix[slot.weekday()][slot.hour] += 1
        weekday = tuple(sum(row) for row in matrix)
        hour = tuple(sum(row[h] for row in matrix) for h in range(24))
        return weekday, hour, tuple(tuple(row) for row in matrix), without_slot

    def _parse_slot_start(self, value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        # Dentalink keeps naive wall-clock times in the clinic timezone, so a naive
        # slot_start is already clinic time; an aware one is converted.
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone(self._tz)

    async def _evidence(
        self,
        period: KpiPeriod,
        taken_rows: list[ConfirmedPendingAction],
        cancelled_rows: list[ConfirmedPendingAction],
    ) -> KpiEvidence:
        operations = [operation for _, operation in EVIDENCE_TOOLS.values()]
        fetched = await self._tool_executions.list_completed_evidence(
            operations,
            period.start - EVIDENCE_BEFORE,
            period.end + EVIDENCE_AFTER,
            self._row_cap + 1,
        )
        truncated = len(fetched) > self._row_cap
        executions = fetched[: self._row_cap]

        # Newest first: when truncated, the dropped executions are all at or before the
        # oldest kept one, so older confirmations cannot be judged either way.
        horizon = min((e.created_at for e in executions), default=None) if truncated else None

        taken_with, taken_unverifiable = _match(
            taken_rows, _evidence_for(ACTION_CREATE, executions), horizon
        )
        cancelled_with, cancelled_unverifiable = _match(
            cancelled_rows, _evidence_for(ACTION_CANCEL, executions), horizon
        )
        return KpiEvidence(
            taken_with=taken_with,
            taken_without=len(taken_rows) - taken_with - taken_unverifiable,
            cancelled_with=cancelled_with,
            cancelled_without=len(cancelled_rows) - cancelled_with - cancelled_unverifiable,
            taken_unverifiable=taken_unverifiable,
            cancelled_unverifiable=cancelled_unverifiable,
            truncated=truncated,
            exact=not truncated,
        )


def _totals(rows: list[ConfirmedPendingAction]) -> PeriodTotals:
    counts = Counter(r.action_type for r in rows)
    return PeriodTotals(
        taken=counts[ACTION_CREATE],
        cancelled=counts[ACTION_CANCEL],
        rescheduled=counts[ACTION_RESCHEDULE],
    )


def _payload_id(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return "" if value is None else str(value).strip()


def _top(
    ids: Iterable[str], resolver: NameResolver | None, *, skip_empty: bool
) -> tuple[TopEntry, ...]:
    """Counts ids, highest first (ties by id). An empty id is skipped, or, for
    specialties, grouped as `NO_SPECIALTY_LABEL` (never sent to the resolver)."""
    counts = Counter(i for i in ids if i or not skip_empty)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_N]
    entries = []
    for id_, count in ranked:
        if id_ == "":
            label = NO_SPECIALTY_LABEL
        else:
            resolved = resolver(id_) if resolver is not None else None
            label = resolved if resolved else id_
        entries.append(TopEntry(id=id_, label=label, count=count))
    return tuple(entries)


def _evidence_for(
    action_type: str, executions: list[ToolExecutionEvidence]
) -> dict[str, list[datetime]]:
    """Creation times of matching executions, per conversation, oldest first."""
    tool_name, operation = EVIDENCE_TOOLS[action_type]
    by_conversation: dict[str, list[datetime]] = {}
    for execution in executions:
        if execution.tool_name == tool_name and execution.operation == operation:
            by_conversation.setdefault(execution.conversation_id, []).append(execution.created_at)
    for times in by_conversation.values():
        times.sort()
    return by_conversation


def _match(
    rows: list[ConfirmedPendingAction],
    evidence: dict[str, list[datetime]],
    horizon: datetime | None,
) -> tuple[int, int]:
    """One-to-one matching: each execution backs at most one confirmation, so two
    confirmations in a conversation are not both 'proven' by a single tool call.

    Returns (matched, unverifiable). With a `horizon` (evidence fetch truncated), an
    unmatched row whose window starts at or before it is unverifiable, not 'without'."""
    matched = 0
    unverifiable = 0
    for row in sorted(rows, key=lambda r: r.confirmed_at):
        times = evidence.get(row.conversation_id, [])
        low = row.confirmed_at - EVIDENCE_BEFORE
        high = row.confirmed_at + EVIDENCE_AFTER
        for index, created_at in enumerate(times):
            if low <= created_at <= high:
                del times[index]
                matched += 1
                break
        else:
            if horizon is not None and low <= horizon:
                unverifiable += 1
    return matched, unverifiable
