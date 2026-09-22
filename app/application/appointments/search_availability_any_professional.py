from datetime import datetime, time, timedelta

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange


class SearchAvailabilityAnyProfessionalUseCase:
    """Aggregates the soonest available slots for a specialty across ALL of
    its enabled professionals (PRD.md has no section for this — most
    patients are new and don't know any professional by name, so being
    forced to pick one before seeing a single slot was pure friction).

    One Dentalink request per calendar day in `date_range`, NOT one per
    (professional, day) pair. `/v5/agendas` with `professional_id=None`
    already returns every professional's slots at the branch for that day
    in a single response — filtering to this specialty's professionals is
    done client-side against the `id_dentista` set from `list_professionals`.
    This is a fix for a real production incident: an earlier version of
    this use case looped `search_availability(professional_id=p.id, ...)`
    per professional, multiplying request volume by the professional count
    (up to 6 professionals x 7 days = 42 sequential requests) and hit a
    live Dentalink `429 Too Many Attempts` — worse than the single-
    professional flow's own earlier 429 incident (an uncapped ~14-day
    walk), despite believing "sequential, not parallel" was enough to stay
    safe. Walking by day instead of by (professional, day) bounds the
    request count to `date_range`'s length regardless of how many
    professionals the specialty has, while keeping the early-cutoff that
    made the per-professional design cheap in the common case: most days
    the first one or two requests already have enough slots, since
    multiple professionals typically have near-term availability.

    Each per-request window is aligned to a single calendar date (the
    caller's own timezone — this use case never needs the clinic's, see
    `app.infrastructure.dentalink.appointment_gateway.
    DentalinkAppointmentGateway.search_availability`, which derives its
    `fecha` filter from `date_range.start.date()`/`date_range.end.date()`
    of whatever `date_range` it's handed). A fix for a second, related
    production issue: this use case used to chunk `date_range` into plain
    now-anchored 24h windows (`day_start`, `day_start + 1 day`) instead of
    calendar-day-aligned ones — a `date_range` starting at, say, 19:58
    turned each one of those 24h windows into a window that itself spans
    TWO calendar dates, doubling the real `/v5/agendas` HTTP call count
    the gateway makes for that one use-case iteration (one per date it
    contains) to up to 14 for a nominal 7-day search. Aligning window ends
    to the next midnight (in whatever tz `date_range` carries) keeps every
    iteration's window within one calendar date, so it costs exactly one
    real HTTP request.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        specialty_id: str,
        date_range: DateTimeRange,
        target_slot_count: int,
    ) -> tuple[list[AppointmentSlot], dict[str, str]]:
        professionals = await self._gateway.list_professionals(specialty_id=specialty_id)
        professional_names = {p.id: p.full_name for p in professionals}
        if not professionals:
            return [], professional_names
        professional_ids = frozenset(professional_names)

        collected: list[AppointmentSlot] = []
        # Dedupe by id, keeping the first occurrence: slot ids are now
        # derived deterministically from professional + start (see
        # `slot_from_agenda`), so a genuine duplicate here would only come
        # from the same slot being re-fetched across overlapping windows —
        # defensive, but cheap insurance against ever re-offering the same
        # id twice in one aggregated list (the root cause of WhatsApp's
        # `[131009] Duplicated row id`).
        seen_ids: set[str] = set()
        day_start = date_range.start
        while day_start < date_range.end:
            midnight_after_day_start = datetime.combine(
                day_start.date() + timedelta(days=1), time.min, tzinfo=day_start.tzinfo
            )
            day_end = min(midnight_after_day_start, date_range.end)
            slots = await self._gateway.search_availability(
                specialty_id=None,
                professional_id=None,
                date_range=DateTimeRange(day_start, day_end),
                limit=None,
            )
            for slot in slots:
                if slot.professional_id not in professional_ids or slot.id in seen_ids:
                    continue
                seen_ids.add(slot.id)
                collected.append(slot)
            day_start = day_end
            if len(collected) >= target_slot_count:
                break

        collected.sort(key=lambda slot: slot.time_range.start)
        return collected[:target_slot_count], professional_names
