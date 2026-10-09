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
#: The welcome list's "Cómo llegar / horarios" row. Routed to the `location` intent
#: (`resolve_interaction.py`), which answers with the clinic image and a "Cómo llegar" button.
MENU_LOCATION_PAYLOAD = "MENU_LOCATION"
#: The "Cómo llegar" button under the clinic image: tapping it returns the native
#: WhatsApp location card (a tap opens the map).
LOCATION_DETAIL_PAYLOAD = "LOCATION_DETAIL"

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
#: Welcome list's "Ver mi cita" row. `appointment.py` routes it to its own
#: read-only view operation: a summary of the upcoming appointments with
#: Reagendar / Cancelar / Menú principal actions. A distinct payload id
#: because WhatsApp list rows must be unique.
OPERATION_VIEW_PAYLOAD = "OPERATION_VIEW"

#: Interactive-list navigation payloads (this change). `LIST_MORE` pages a
#: list forward (the pagination position lives in `collected_data`);
#: `LIST_BACK` pops one screen off the per-conversation navigation stack.
#: `LIST_PREV` pages a list backward by exactly one page (slot lists only); it
#: is deliberately distinct from `LIST_BACK`, which means "leave this screen".
LIST_MORE_PAYLOAD = "LIST_MORE"
LIST_BACK_PAYLOAD = "LIST_BACK"
LIST_PREV_PAYLOAD = "LIST_PREV"

#: Row-id prefixes for the paginated specialty/professional lists — stable
#: ids round-trip through WhatsApp's `list_reply.id` (parsed into
#: `button_payload` by `webhook_parser.py`).
SPECIALTY_PAYLOAD_PREFIX = "SPECIALTY:"
PROFESSIONAL_PAYLOAD_PREFIX = "PROFESSIONAL:"

#: Shown only when "ver próximos turnos" (a valid specialty pick now goes
#: straight there, no intermediate screen — PRD.md has no section for it,
#: most patients are new and don't know any professional by name) finds
#: nothing to offer: lets the patient fall back to picking a specific
#: professional's full agenda instead. "Otra especialidad", the other way
#: out of that same fallback screen, deliberately reuses `LIST_BACK_PAYLOAD`
#: rather than getting its own id — it means the same thing ("pop one level
#: up") that payload already means everywhere else in this flow.
CHOOSE_PROFESSIONAL_PAYLOAD = "CHOOSE_PROFESSIONAL"

#: The "no patient found" choice shown when identification finds no Dentalink match:
#: register as a new patient (first-visit intake, name and DNI prefilled) or retry with
#: other data. The third option, talking to an advisor, reuses `MENU_ADMIN_PAYLOAD`.
PATIENT_NOT_FOUND_REGISTER_PAYLOAD = "PATIENT_NOT_FOUND_REGISTER"
PATIENT_NOT_FOUND_RETRY_PAYLOAD = "PATIENT_NOT_FOUND_RETRY"

#: The typed name and DNI are echoed back before any Dentalink lookup: confirm to look the
#: patient up, or modify to type the data again.
IDENTIFICATION_CONFIRM_PAYLOAD = "IDENTIFICATION_CONFIRM"
IDENTIFICATION_MODIFY_PAYLOAD = "IDENTIFICATION_MODIFY"

#: "Consultas frecuentes" (clinic FAQ topics). `MENU_FAQ_PAYLOAD` opens the sub-list of
#: topics; each topic row carries `FAQ_TOPIC_PAYLOAD_PREFIX` + the topic id defined in
#: `app.agent.clinic_topics`, which round-trips through WhatsApp's `list_reply.id`.
MENU_FAQ_PAYLOAD = "MENU_FAQ"
FAQ_TOPIC_PAYLOAD_PREFIX = "FAQ_TOPIC:"
FAQ_TOPIC_BLANQUEAMIENTO_PAYLOAD = "FAQ_TOPIC:blanqueamiento"
FAQ_TOPIC_CONSULTA_PAYLOAD = "FAQ_TOPIC:consulta_particular"
FAQ_TOPIC_LIMPIEZA_PAYLOAD = "FAQ_TOPIC:limpieza_particular"
FAQ_TOPIC_BRACKETS_PAYLOAD = "FAQ_TOPIC:brackets_obra_social"
FAQ_TOPIC_ALINEADORES_PAYLOAD = "FAQ_TOPIC:alineadores"

#: "Agendar cita" button of a topic answer that books a fixed Dentalink specialty
#: (consulta particular -> "General"): `FAQ_BOOK:` + the topic id. Distinct from
#: `OPERATION_CREATE_PAYLOAD`, which starts a booking with no specialty chosen.
FAQ_BOOK_PAYLOAD_PREFIX = "FAQ_BOOK:"
#: One of a topic's option buttons (alineadores -> `Opción 1..3`): `FAQ_OPTION:` + the
#: topic id + `:` + the option. Choosing one starts the booking and remembers the option.
FAQ_OPTION_PAYLOAD_PREFIX = "FAQ_OPTION:"
_MAX_PAYLOAD_LENGTH = 256


def faq_book_payload(topic_id: str) -> str:
    payload = f"{FAQ_BOOK_PAYLOAD_PREFIX}{topic_id}"
    if len(payload) > _MAX_PAYLOAD_LENGTH:
        raise ValueError(f"button id longer than {_MAX_PAYLOAD_LENGTH} characters: {payload}")
    return payload


def faq_option_payload(topic_id: str, option: str) -> str:
    payload = f"{FAQ_OPTION_PAYLOAD_PREFIX}{topic_id}:{option}"
    if len(payload) > _MAX_PAYLOAD_LENGTH:
        raise ValueError(f"button id longer than {_MAX_PAYLOAD_LENGTH} characters: {payload}")
    return payload


def parse_faq_option_payload(payload: str) -> tuple[str, str] | None:
    """`(topic_id, option)` of a `FAQ_OPTION:<topic>:<option>` payload, else None."""
    if not payload.startswith(FAQ_OPTION_PAYLOAD_PREFIX):
        return None
    topic_id, separator, option = payload.removeprefix(FAQ_OPTION_PAYLOAD_PREFIX).partition(":")
    if not separator or not topic_id or not option:
        return None
    return topic_id, option
