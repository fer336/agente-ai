from datetime import date

from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange


class SearchAvailabilityAnyProfessionalUseCase:
    """Aggregates the soonest available slots for a specialty across
    several of its professionals (PRD.md has no section for this — most
    patients are new and don't know any professional by name, so being
    forced to pick one before seeing a single slot was pure friction).

    Sequential across professionals, with an early cutoff, deliberately —
    NOT `asyncio.gather`-style bounded parallelism. This session's own
    production incident (a live Dentalink `429 Too Many Attempts`) came
    from ONE professional's uncapped day-by-day walk firing requests back
    to back with no pause, which suggests the limiter reacts to request
    BURST rate, not just total count over time. Firing several
    professionals' searches concurrently would compress the same request
    volume into a shorter wall-clock window — a real burst — which is
    strictly more likely to reproduce that 429, not less. Sequential-with-
    early-cutoff is also cheaper in the common case: it never fires a
    second professional's search once the first already supplied enough
    slots, where a batch-parallel design would have already paid for the
    whole batch before it could check that.
    """

    def __init__(self, gateway: AppointmentGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        specialty_id: str,
        date_range: DateTimeRange,
        target_slot_count: int,
        max_professionals_attempted: int,
    ) -> tuple[list[AppointmentSlot], dict[str, str]]:
        professionals = await self._gateway.list_professionals(specialty_id=specialty_id)
        professional_names = {p.id: p.full_name for p in professionals}
        if not professionals:
            return [], professional_names

        # A fixed, un-rotated order would mean the same first N
        # professionals are always the ones whose slots get shown, every
        # turn, forever — unfair to the rest of the specialty's
        # professionals and worse for patients (never surfacing a closer
        # slot a later professional actually has). A daily rotation costs
        # nothing (no new persisted state) and stays stable within one day,
        # so a patient paging back and forth mid-conversation never sees
        # the candidate pool shift under them — moot in practice anyway
        # since the gathered slots are cached in `collected_data` and
        # pagination never re-searches.
        offset = date.today().toordinal() % len(professionals)
        rotated = professionals[offset:] + professionals[:offset]

        collected: list[AppointmentSlot] = []
        for professional in rotated[:max_professionals_attempted]:
            remaining = target_slot_count - len(collected)
            if remaining <= 0:
                break
            slots = await self._gateway.search_availability(
                specialty_id=None,
                professional_id=professional.id,
                date_range=date_range,
                limit=remaining,
            )
            collected.extend(slots)

        collected.sort(key=lambda slot: slot.time_range.start)
        return collected[:target_slot_count], professional_names
