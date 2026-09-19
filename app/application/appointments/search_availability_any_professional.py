from datetime import timedelta

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
        day_start = date_range.start
        while day_start < date_range.end:
            day_end = min(day_start + timedelta(days=1), date_range.end)
            slots = await self._gateway.search_availability(
                specialty_id=None,
                professional_id=None,
                date_range=DateTimeRange(day_start, day_end),
                limit=None,
            )
            collected.extend(slot for slot in slots if slot.professional_id in professional_ids)
            day_start = day_end
            if len(collected) >= target_slot_count:
                break

        collected.sort(key=lambda slot: slot.time_range.start)
        return collected[:target_slot_count], professional_names
