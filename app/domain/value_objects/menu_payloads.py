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
#: PRD.md §7's welcome menu's third option (this change) — surfaces the
#: not-yet-built specialties lookup, distinct from `MENU_INSURANCE_PAYLOAD`'s
#: separate, already-built obra social/prepaga flow.
MENU_SPECIALTIES_PAYLOAD = "MENU_SPECIALTIES"
