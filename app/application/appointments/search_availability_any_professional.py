from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange


class SearchAvailabilityAnyProfessionalUseCase:
    """Aggregates the soonest available slots for a specialty across ALL of
    its enabled professionals (PRD.md has no section for this — most
    patients are new and don't know any professional by name, so being
    forced to pick one before seeing a single slot was pure friction).

    The search is scoped BY SPECIALTY: `AppointmentGateway.
    search_specialty_availability` asks Dentalink for that specialty's slots
    (server-side `id_especialidad` filter) and walks forward from the start
    of `date_range` with a bounded number of requests — see its own docstring
    for the walk. This replaced a per-calendar-day query of the WHOLE
    branch's agenda filtered client-side: `/v5/agendas` answers at most 10
    rows per request, so on every day the general dentists filled the response
    and a specialty with few professionals (Endodoncia, Ortodoncia) was cut
    off to an empty result.

    Two earlier designs caused real production incidents and must not come
    back: looping `search_availability` once per professional (up to
    6 professionals x 7 days = 42 sequential requests -> live Dentalink
    `429 Too Many Attempts`), and chunking the range into now-anchored 24h
    windows that each spanned two calendar dates (double the requests). The
    request count is now bounded inside the gateway, independent of the
    window length and of how many professionals the specialty has.

    `list_professionals` still runs, for two reasons: it provides the
    professional names (used only to keep a name out of the chat text), and
    it is a safety net — a slot from anyone who is not an enabled
    professional of the specialty (e.g. a disabled one the agenda still
    lists) is never offered. The server-side filter and this set agree on
    enabled professionals (a dentist carries a single `id_especialidad`),
    so the net does not hide valid slots.
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

        slots = await self._gateway.search_specialty_availability(
            specialty_id=specialty_id,
            date_range=date_range,
            limit=target_slot_count,
        )

        collected: list[AppointmentSlot] = []
        # Dedupe by id, keeping the first occurrence: slot ids are derived
        # deterministically from professional + start (see
        # `slot_from_agenda`), so this is cheap insurance against ever
        # re-offering the same id twice in one aggregated list (the root
        # cause of WhatsApp's `[131009] Duplicated row id`).
        seen_ids: set[str] = set()
        for slot in slots:
            if slot.professional_id not in professional_ids or slot.id in seen_ids:
                continue
            seen_ids.add(slot.id)
            collected.append(slot)

        collected.sort(key=lambda slot: slot.time_range.start)
        return collected[:target_slot_count], professional_names
