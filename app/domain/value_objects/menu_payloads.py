"""Deterministic welcome-menu button payload ids (PRD.md §6-7).

Shared between `app.agent.nodes.resolve_interaction` (routes an inbound
button tap to its known intent) and `app.application.messages.ingest_message`
(sends these same ids as the first-turn welcome message's buttons). Living in
`app.domain` — rather than in `app.agent.nodes.resolve_interaction`, where
they were originally introduced — is deliberate: `app.agent` nodes already
import from `app.application` (e.g. `agreement.py` -> `ListAgreementsUseCase`),
so the reverse import (`app.application` -> `app.agent`) would invert this
codebase's one-way hexagonal dependency direction. `resolve_interaction.py`
still imports these names, so it keeps exposing them at their original
location for any existing importer.
"""

MENU_APPOINTMENT_PAYLOAD = "MENU_APPOINTMENT"
MENU_INSURANCE_PAYLOAD = "MENU_INSURANCE"
MENU_ADMIN_PAYLOAD = "MENU_ADMIN"
#: Explicit escape from an in-progress flow back to the canonical principal menu.
MENU_MAIN_PAYLOAD = "MENU_MAIN"
#: PRD.md §7's welcome menu's third option (this change) — surfaces the
#: not-yet-built specialties lookup, distinct from `MENU_INSURANCE_PAYLOAD`'s
#: separate, already-built obra social/prepaga flow.
MENU_SPECIALTIES_PAYLOAD = "MENU_SPECIALTIES"
#: The welcome list's "Cómo llegar / horarios" row (this session's own
#: brief). Deliberately NOT added to `resolve_interaction.py`'s
#: `_MENU_BUTTON_INTENTS` — falling through as "unknown" routes it to
#: `fallback.py`, whose `_asks_for_location` keyword match already fires
#: on this exact row title ("cómo llegar"), sending the real location
#: card. A dedicated intent would just duplicate that.
MENU_LOCATION_PAYLOAD = "MENU_LOCATION"

#: Button payload contract for `app.agent.nodes.appointment`'s operation
#: selection (PRD.md §6: deterministic, never LLM-classified) — living
#: here for the same reason as the `MENU_*` payloads above: the welcome
#: list (`app.application.messages.ingest_message`) sends these same ids
#: directly on its booking rows, skipping `STAGE_AWAITING_OPERATION_SELECTION`'s
#: menu entirely, so `app.application` needs them without importing
#: `app.agent`.
OPERATION_CREATE_PAYLOAD = "OPERATION_CREATE"
OPERATION_RESCHEDULE_PAYLOAD = "OPERATION_RESCHEDULE"
OPERATION_CANCEL_PAYLOAD = "OPERATION_CANCEL"
#: Welcome list's "Ver mi cita" row (this session's own brief — the
#: client hasn't defined a genuine read-only view yet). `appointment.py`
#: provisionally routes this through the same "list my appointments" step
#: RESCHEDULE already reaches — a distinct payload id (WhatsApp list rows
#: must be unique) mapped to the same operation, not a new one, until the
#: client decides what "just viewing" should actually do differently.
OPERATION_VIEW_PAYLOAD = "OPERATION_VIEW"

#: Interactive-list navigation payloads (this change). `LIST_MORE` pages a
#: list forward (the pagination position lives in `collected_data`);
#: `LIST_BACK` pops one screen off the per-conversation navigation stack.
LIST_MORE_PAYLOAD = "LIST_MORE"
LIST_BACK_PAYLOAD = "LIST_BACK"

#: Row-id prefixes for the paginated specialty/professional lists — stable
#: ids round-trip through WhatsApp's `list_reply.id` (parsed into
#: `button_payload` by `webhook_parser.py`).
SPECIALTY_PAYLOAD_PREFIX = "SPECIALTY:"
PROFESSIONAL_PAYLOAD_PREFIX = "PROFESSIONAL:"
