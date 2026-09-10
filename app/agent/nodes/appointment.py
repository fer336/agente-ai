import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from redis.asyncio import Redis

from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.appointments.cancel_appointment import CancelAppointmentUseCase
from app.application.appointments.get_patient_appointments import GetPatientAppointmentsUseCase
from app.application.appointments.propose_appointment import (
    ProposalRepositories,
    ProposalRepositoriesProvider,
    ProposeAppointmentUseCase,
)
from app.application.appointments.revalidate_and_create_appointment import (
    RevalidateAndCreateAppointmentUseCase,
)
from app.application.appointments.revalidate_and_reschedule_appointment import (
    RevalidateAndRescheduleAppointmentUseCase,
)
from app.application.appointments.search_availability import SearchAvailabilityUseCase
from app.application.conversations.rotate_workflow_session import RotateWorkflowSessionUseCase
from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    INTERACTIVE_SELECTION,
    SENSITIVE_CONFIRMATION,
    SetConversationInputStateUseCase,
)
from app.application.patients.identify_patient import IdentifyPatientUseCase
from app.application.pending_actions.confirm_pending_action import ConfirmPendingActionUseCase
from app.application.pending_actions.reject_pending_action import RejectPendingActionUseCase
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.entities.professional import Professional
from app.domain.entities.specialty import Specialty
from app.domain.exceptions.errors import (
    AppointmentSlotUnavailableError,
    InvalidConfirmationError,
    PatientAlreadyExistsError,
    PendingActionExpiredError,
)
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import (
    AgreementGateway,
    AppointmentGateway,
    PatientGateway,
    SpecialtyGateway,
)
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.dni import Dni
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.flow_response import parse_flow_response_payload
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.domain.value_objects.paginated_list import (
    professionals_list_message,
    specialties_list_message,
)
from app.domain.value_objects.phone_number import PhoneNumber
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.ycloud.flows import (
    REGISTRATION_FLOW_SCREEN_ID,
    VERIFICATION_FLOW_SCREEN_ID,
)

#: Each day in the window is one sequential Dentalink request (the API only
#: filters `fecha` by exact day, never by range — see the gateway's own
#: docstring). A 30-day window meant walking up to 30 requests before ever
#: reaching "no hay turnos", which was enough on its own to trip Dentalink's
#: undocumented rate limit. 14 trades a little reach for far fewer requests.
_SEARCH_WINDOW = timedelta(days=14)
#: WhatsApp/Meta rejects an interactive message with more than 3 reply
#: buttons. Nothing downstream (`SendReplyUseCase`, `YCloudMessagingGateway`,
#: `YCloudClient`) enforces it, so every button list is capped here.
_MAX_OPTIONS_SHOWN = 3

#: `collected_data["stage"]` values — this node's own multi-turn cursor
#: (PRD.md §9-14's flows). `resolve_interaction` only checks whether a
#: stage is set at all (routing any button/free-text turn straight back
#: here, PRD.md §24.2); this node alone interprets which one.
STAGE_AWAITING_OPERATION_SELECTION = "awaiting_operation_selection"
#: Booking a NEW appointment starts here (this session's brief): the
#: patient picks a specialty, then one of that specialty's professionals,
#: and only then sees real availability. Both are numbered TEXT lists,
#: not buttons — WhatsApp caps interactive replies at 3 and this clinic
#: has 16 specialties. Neither is a sensitive write, so both run under
#: `FREE_INPUT` (PRD.md §24.2 reserves button-only input for selections
#: and confirmations that mutate something).
STAGE_AWAITING_SPECIALTY_SELECTION = "awaiting_specialty_selection"
STAGE_AWAITING_PROFESSIONAL_SELECTION = "awaiting_professional_selection"
STAGE_AWAITING_IDENTIFICATION = "awaiting_identification"
#: Flow-based identification (this session's own brief, no PRD.md
#: section): sent instead of `STAGE_AWAITING_IDENTIFICATION`'s free-text
#: ask whenever `verification_flow_id` is configured — see
#: `_begin_identification`. A found patient moves to
#: `STAGE_AWAITING_VERIFICATION_CONFIRMATION` to confirm the data is
#: really theirs before it's ever used; not-found (or a rejected
#: confirmation) moves straight to `STAGE_AWAITING_REGISTRATION_FLOW`.
STAGE_AWAITING_VERIFICATION_FLOW = "awaiting_verification_flow"
STAGE_AWAITING_VERIFICATION_CONFIRMATION = "awaiting_verification_confirmation"
STAGE_AWAITING_REGISTRATION_FLOW = "awaiting_registration_flow"
STAGE_AWAITING_APPOINTMENT_SELECTION = "awaiting_appointment_selection"
STAGE_AWAITING_SLOT_SELECTION = "awaiting_slot_selection"
STAGE_AWAITING_CONFIRMATION = "awaiting_confirmation"
#: No slots for the chosen professional: offer other professionals of the
#: same specialty before ever mentioning administración (product brief —
#: jumping straight to "quieres hablar con administración" reads as giving
#: up on the patient too fast when other professionals might still have room).
STAGE_AWAITING_NO_SLOTS_CHOICE = "awaiting_no_slots_choice"
STAGE_AWAITING_NO_AVAILABILITY_CHOICE = "awaiting_no_availability_choice"
#: Reschedule used to search every professional in the clinic for a new
#: slot (product brief: seen live showing a completely different
#: specialty than the original appointment) — now the patient is asked
#: first whether to keep the same professional or pick another.
STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE = "awaiting_reschedule_professional_choice"

#: `PendingAction.action_type` values (PRD.md §16's documented enum) — also
#: doubles as `collected_data["operation"]` while a proposal doesn't exist
#: yet, so the same three tokens drive both "which sub-flow is this turn
#: in" (pre-proposal) and "which execution runs on confirm" (post-proposal,
#: read from the durably confirmed `PendingAction` itself, not
#: `collected_data` — see this function's own docstring).
CREATE_APPOINTMENT_ACTION = "create_appointment"
RESCHEDULE_APPOINTMENT_ACTION = "reschedule_appointment"
CANCEL_APPOINTMENT_ACTION = "cancel_appointment"

#: A fourth `PendingAction.action_type`, alongside the three above — only
#: ever proposed from `STAGE_AWAITING_IDENTIFICATION` when the patient
#: could not be found AND the in-flight operation is
#: `CREATE_APPOINTMENT_ACTION` (rescheduling/cancelling a nonexistent
#: patient's appointment makes no sense, so this is never offered for
#: those two operations). Reuses the same generic
#: `STAGE_AWAITING_CONFIRMATION` confirm/reject cycle as the other three.
CREATE_PATIENT_ACTION = "create_patient"

#: `UnderstandingResult.operation_mention` -> this node's own action
#: tokens, so a patient who says "quiero cancelar mi turno" skips the
#: operation menu they already answered in words.
_OPERATION_BY_MENTION = {
    "create": CREATE_APPOINTMENT_ACTION,
    "reschedule": RESCHEDULE_APPOINTMENT_ACTION,
    "cancel": CANCEL_APPOINTMENT_ACTION,
}

#: Shared by `STAGE_AWAITING_OPERATION_SELECTION` (tapped from that stage's
#: own menu) and the "no stage yet" fallback (tapped directly from the
#: welcome list, skipping that menu entirely) — one mapping, so both entry
#: points can never drift out of sync with each other.
_OPERATION_BY_PAYLOAD = {
    OPERATION_CREATE_PAYLOAD: CREATE_APPOINTMENT_ACTION,
    OPERATION_RESCHEDULE_PAYLOAD: RESCHEDULE_APPOINTMENT_ACTION,
    OPERATION_CANCEL_PAYLOAD: CANCEL_APPOINTMENT_ACTION,
    OPERATION_VIEW_PAYLOAD: RESCHEDULE_APPOINTMENT_ACTION,
}
SELECT_APPOINTMENT_PAYLOAD_PREFIX = "SELECT_APPOINTMENT:"
SELECT_SLOT_PAYLOAD_PREFIX = "SELECT_SLOT:"
CONFIRM_APPOINTMENT_PAYLOAD = "CONFIRM_APPOINTMENT"
REJECT_APPOINTMENT_PAYLOAD = "REJECT_APPOINTMENT"
RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD = "RESCHEDULE_KEEP_PROFESSIONAL"
RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD = "RESCHEDULE_CHANGE_PROFESSIONAL"

#: No upper bound on digit count here — `Dni` (7-8 digits) is the real
#: gatekeeper for validity. Capping this at 9 used to truncate a longer
#: run (e.g. a 10-digit typo) and leak the leftover digit into the parsed
#: name instead of the whole thing failing `Dni`'s length check cleanly.
_DNI_PATTERN = re.compile(r"(\d{6,})")

_CHOOSE_SPECIALTY_PROMPT = "Para qué especialidad querés el turno? Respondeme con el número:"
_SPECIALTY_NOT_UNDERSTOOD_MESSAGE = (
    "No pude identificar la especialidad. Respondeme con el número de la lista:"
)
_NO_SPECIALTIES_MESSAGE = (
    "En este momento no tengo las especialidades disponibles. "
    "Querés que te comunique con administración?"
)
_CHOOSE_PROFESSIONAL_PROMPT = "Con qué profesional preferís atenderte? Respondeme con el número:"
_PROFESSIONAL_NOT_UNDERSTOOD_MESSAGE = (
    "No pude identificar al profesional. Respondeme con el número de la lista:"
)
_NO_PROFESSIONALS_MESSAGE = (
    "No tengo profesionales cargados para esa especialidad. "
    "Querés que te comunique con administración?"
)
_OPERATION_MENU_MESSAGE = "Qué querés hacer?"
_MAIN_MENU_RESET_MESSAGE = "Listo, volvemos al principio. Qué querés hacer?"
_OPERATION_SELECTION_REMINDER = "Por favor, elegí una opción tocando un botón."
_ASK_IDENTIFICATION_MESSAGE = (
    "Para coordinar un turno necesito identificarte primero.\n\n"
    "Escribime tu *nombre completo* y tu *DNI* (por ejemplo: Rosa Gómez, 30123456)."
)
_IDENTIFICATION_NOT_UNDERSTOOD_MESSAGE = (
    "No pude leer bien tus datos. Escribime tu nombre completo y tu DNI juntos, "
    "por ejemplo: Rosa Gómez, 30123456."
)
_PATIENT_NOT_FOUND_MESSAGE = (
    "No encontramos ningún paciente con esos datos. Revisá que el nombre y el DNI "
    "coincidan exactamente con los registrados en la clínica, y probá de nuevo."
)
_DNI_FORMAT_INVALID_MESSAGE = (
    "Ese DNI no parece válido. Escribime tu DNI solo con números "
    "(7 u 8 dígitos), por ejemplo: 30123456."
)
_NAME_INCOMPLETE_MESSAGE = (
    "Necesito tu nombre Y apellido completos, no solo uno. Escribimelos junto "
    "con tu DNI, por ejemplo: Rosa Gómez, 30123456."
)
_ASK_DNI_ONLY_MESSAGE = "Gracias! Ahora decime tu *DNI* (7 u 8 dígitos), por ejemplo: 30123456."
_ASK_NAME_ONLY_MESSAGE = "Gracias! Ahora decime tu *nombre completo*, por ejemplo: Rosa Gómez."
_NEW_PATIENT_RACE_LOST_MESSAGE = (
    "Encontramos un registro para ese DNI, pero con otro nombre. Por seguridad, "
    "escribime de nuevo tu nombre completo y tu DNI para verificarlo."
)
_SEND_VERIFICATION_FLOW_MESSAGE = (
    "Te mando un formulario cortito para verificar tus datos — tocá el botón de abajo."
)
_SEND_REGISTRATION_FLOW_MESSAGE = (
    "No te encontramos registrado todavía. Te mando un formulario para completar tus "
    "datos — tocá el botón de abajo."
)
_FLOW_REMINDER_MESSAGE = (
    "Por favor, completá el formulario que te mandé arriba — todavía no puedo tomar "
    "estos datos por texto."
)
_NO_SLOTS_MESSAGE = (
    "No encontramos horarios disponibles en los próximos días. "
    "Querés que te comunique con administración?"
)
_NO_SLOTS_OTHER_PROFESSIONALS_MESSAGE = (
    "No encontramos horarios disponibles con ese profesional en los próximos días. "
    "¿Querés ver otros profesionales de la misma especialidad?"
)
_NO_APPOINTMENTS_MESSAGE = (
    "No encontramos turnos próximos a tu nombre. Querés que te comunique con administración?"
)
_CHOOSE_SLOT_PROMPT = "Elegí un horario tocando uno de los botones:"
_SLOT_SELECTION_REMINDER = (
    "Por favor, elegí uno de los horarios tocando un botón — todavía no puedo "
    "tomar la selección por texto."
)
_STALE_SLOT_SELECTION_MESSAGE = "Esa opción ya no está disponible. Elegí una de estas:"
_CHOOSE_APPOINTMENT_PROMPT = "Elegí el turno tocando uno de los botones:"
_APPOINTMENT_SELECTION_REMINDER = (
    "Por favor, elegí uno de tus turnos tocando un botón — todavía no puedo "
    "tomar la selección por texto."
)
_STALE_APPOINTMENT_SELECTION_MESSAGE = "Esa opción ya no está disponible. Elegí una de estas:"
_CONFIRMATION_REMINDER = (
    "Por favor, confirmá o cancelá tocando uno de los botones — todavía no puedo "
    "tomar la confirmación por texto."
)
_PROPOSAL_REJECTED_MESSAGE = "Listo, descartamos esa propuesta. Necesitás algo más?"
_SLOT_TAKEN_MESSAGE = (
    "Ese horario acaba de ocuparse mientras confirmábamos. No se realizó ningún cambio. "
    "Te muestro nuevas opciones disponibles:"
)
_PROPOSAL_NO_LONGER_VALID_MESSAGE = "Esa propuesta ya no está vigente. Busquemos otro horario:"
_PROPOSAL_NOT_FOUND_MESSAGE = (
    "No encontramos esa propuesta. Empecemos de nuevo — querés sacar un turno?"
)
_SESSION_LOST_MESSAGE = (
    "Se perdió el contexto de la conversación. Escribime de nuevo qué necesitás."
)

_OPERATION_BUTTONS = [
    InteractiveButton(id=OPERATION_CREATE_PAYLOAD, title="📅 Sacar turno"),
    InteractiveButton(id=OPERATION_RESCHEDULE_PAYLOAD, title="🔄 Reagendar"),
    InteractiveButton(id=OPERATION_CANCEL_PAYLOAD, title="❌ Cancelar"),
]
_CONFIRM_BUTTONS = [
    InteractiveButton(id=CONFIRM_APPOINTMENT_PAYLOAD, title="✅ Confirmar"),
    InteractiveButton(id=REJECT_APPOINTMENT_PAYLOAD, title="❌ Cancelar"),
]
#: Tapping any of these abandons whatever stage is in flight — see `node`.
#: `MENU_ADMIN_PAYLOAD` is deliberately NOT here: `resolve_interaction.py`
#: now routes it to `intent="handoff"` before this node ever runs, so it
#: can never arrive as `button_payload` mid-stage any more. The 4
#: `OPERATION_*` payloads are the welcome list's own booking rows (bug
#: found live: the same WhatsApp number reused across a leftover
#: `STAGE_AWAITING_IDENTIFICATION` from an earlier reschedule/cancel test —
#: tapping "Agendar una cita" from a freshly resent welcome menu was
#: silently swallowed by that stale stage instead of starting the tapped
#: operation, since only the two generic menu buttons reset it) — without
#: them here, a stale stage always wins over an explicit new pick.
_MAIN_MENU_PAYLOADS = frozenset(
    {
        MENU_APPOINTMENT_PAYLOAD,
        MENU_SPECIALTIES_PAYLOAD,
        OPERATION_CREATE_PAYLOAD,
        OPERATION_RESCHEDULE_PAYLOAD,
        OPERATION_CANCEL_PAYLOAD,
        OPERATION_VIEW_PAYLOAD,
    }
)
#: How many consecutive unreadable identification attempts before the
#: patient is offered a human instead. Mirrors `fallback.py`'s own ceiling:
#: without one, `identification_retry_count` just counted upward while the
#: patient rewrote their DNI forever.
_ESCALATE_IDENTIFICATION_AFTER_ATTEMPTS = 2
_IDENTIFICATION_ESCAPE_BUTTONS = [
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="👤 Administración"),
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="🔄 Empezar de nuevo"),
]
#: Product brief: the specialty/professional selection stages used numbered
#: TEXT lists with no way out at all — a patient who changed their mind
#: mid-list had no button to tap, only the admin-escalation phrase (PRD.md
#: §24.2). One button is safe to add there (WhatsApp caps interactive
#: replies at 3, and these stages send none of their own).
_MAIN_MENU_BUTTON = InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Volver al Menú")
#: `MENU_ADMIN_PAYLOAD` here is never handled inside this stage: any button
#: with that payload is intercepted upstream by `resolve_interaction.py`,
#: which routes it straight to `intent="handoff"` regardless of the active
#: stage — the same mechanism `_IDENTIFICATION_ESCAPE_BUTTONS` relies on.
_VIEW_OTHER_PROFESSIONALS_PAYLOAD = "VIEW_OTHER_PROFESSIONALS"
_NO_SLOTS_CHOICE_BUTTONS = [
    InteractiveButton(id=_VIEW_OTHER_PROFESSIONALS_PAYLOAD, title="🔎 Ver otros profesionales"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="👤 Administración"),
]
_NO_AVAILABILITY_BUTTONS = [
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="Administración"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]
_RESCHEDULE_PROFESSIONAL_CHOICE_BUTTONS = [
    InteractiveButton(id=RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD, title="✅ Mismo profesional"),
    InteractiveButton(id=RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD, title="🔄 Elegir otro"),
]
_RESCHEDULE_PROFESSIONAL_CHOICE_REMINDER = (
    "Por favor, elegí una opción tocando un botón: mantener el mismo profesional o elegir otro."
)


<<<<<<< Updated upstream
#: Words that never appear in a real full name but commonly appear in
#: ordinary chatter — used to keep a name-only, no-digit message from being
#: misread as identification when it's actually just conversation ("hola
#: quiero un turno"). Deliberately small and Spanish-specific (PRD.md's own
#: language): a false negative here just means one extra retry prompt, a
#: false positive means silently losing a real name to `_merge_identification`
#: discarding it as noise — the worse failure mode, per the bug this list
#: guards against (see `_merge_identification`'s docstring).
_NON_NAME_WORDS = frozenset(
    {
        "hola",
        "buenas",
        "buenos",
        "dias",
        "días",
        "tardes",
        "noches",
        "quiero",
        "queria",
        "quería",
        "querria",
        "querría",
        "quisiera",
        "necesito",
        "turno",
        "turnos",
        "cita",
        "consulta",
        "gracias",
        "porfavor",
        "porfa",
        "ayuda",
        "informacion",
        "información",
        "saber",
        "como",
        "cómo",
        "cuando",
        "cuándo",
        "donde",
        "dónde",
        "que",
        "qué",
        "hacer",
        "sacar",
        "reservar",
        "cancelar",
        "reagendar",
        "administracion",
        "administración",
        "hablar",
        "persona",
        "humano",
        "no",
        "si",
        "sé",
        "se",
        "estoy",
        "soy",
        "registrado",
        "registrada",
        "creo",
        "puedo",
        "podes",
        "podés",
        "puede",
    }
)
=======
def _fresh_tramite() -> dict[str, object]:
    """The ONE way to end a trámite and drop its cursor (PRD.md brief: "no
    queden datos colgados anteriores").

    Every terminal return in `node()` — success, an unrecoverable dead end,
    a rejected/expired proposal, the main-menu escape hatch — MUST build
    its `collected_data` from this, never a literal `{}`. A hand-written
    `{}` anywhere else in this file is a bug waiting to happen: it was
    exactly a `return` that forgot to touch `collected_data` at all (not
    even `{}`) that once trapped a patient in `STAGE_AWAITING_IDENTIFICATION`
    forever, since the previous stage-carrying state simply persisted.
    A fresh `dict` per call, not a shared module-level literal, so nothing
    downstream can ever mutate a "constant" shared across turns/patients.
    """
    return {}


def _parse_identification(text: str) -> tuple[str, str] | None:
    """Extracts (full_name, dni) from free text (PRD.md §32).
>>>>>>> Stashed changes


def _looks_like_a_name(text: str) -> bool:
    """True when a no-digit message reads as a plausible full name rather
    than ordinary chatter — see `_NON_NAME_WORDS`."""
    words = text.casefold().split()
    return bool(words) and not any(word.strip(".,!?¡¿") in _NON_NAME_WORDS for word in words)


def _extract_identification_pieces(text: str) -> tuple[str | None, str | None]:
    """Splits free text into whichever (full_name, dni) pieces it actually
    contains — either can be missing, since the patient may answer across
    two messages instead of PRD.md §32's suggested one-shot format
    ("Rosa Gómez, 30123456"). A 6+ digit run anywhere is the DNI and
    whatever surrounds it is the name; with no digit run at all, the
    message is a name-only answer UNLESS it reads as ordinary chatter (see
    `_looks_like_a_name`) — that check only matters here, since a DNI's
    presence is already unambiguous proof of an identification attempt.
    """
    match = _DNI_PATTERN.search(text)
    if match is not None:
        dni = match.group(1)
        full_name = re.sub(r"\s+", " ", text[: match.start()] + text[match.end() :]).strip(" ,.-")
        return full_name or None, dni
    stripped = text.strip()
    if not stripped or not _looks_like_a_name(stripped):
        return None, None
    return stripped, None


#: A patient answering a numbered list types "2", "2." or "opción 2" —
#: never more than three digits, since no catalog here is that long.
_NUMBERED_CHOICE_PATTERN = re.compile(r"\b(\d{1,3})\b")


def _resolve_numbered_choice(text: str, option_count: int) -> int | None:
    """Maps a patient's 1-based reply to a 0-based index into the list they
    were just shown, or `None` when it isn't a number in range."""
    match = _NUMBERED_CHOICE_PATTERN.search(text)
    if match is None:
        return None
    index = int(match.group(1)) - 1
    return index if 0 <= index < option_count else None


def _resolve_by_name(text: str, names: list[str]) -> int | None:
    """Falls back to matching a catalog name found inside the message —
    same idiom `agreement.py` already uses for obra social names, so a
    patient who types "quiero ortodoncia" instead of "1" still gets
    through."""
    lowered = text.casefold()
    for index, name in enumerate(names):
        if name.casefold() in lowered:
            return index
    return None


def _resolve_choice(text: str, names: list[str]) -> int | None:
    """Number first (what the list explicitly asked for), name second."""
    by_number = _resolve_numbered_choice(text, len(names))
    if by_number is not None:
        return by_number
    return _resolve_by_name(text, names)


def _numbered_list(names: list[str]) -> str:
    return "\n".join(f"{position}. {name}" for position, name in enumerate(names, start=1))


def resolve_by_name(text: str, names: list[str]) -> int | None:
    """Public alias of `_resolve_by_name` for `specialties.py`, which hands
    a named specialty straight into this node's professional-selection
    stage and must match names exactly the way this node does."""
    return _resolve_by_name(text, names)


def numbered_list(names: list[str]) -> str:
    """Public alias of `_numbered_list` — same reason as `resolve_by_name`."""
    return _numbered_list(names)


async def staffed_specialty_ids(gateway: AppointmentGateway) -> set[str]:
    """Specialty ids that at least one professional actually teaches.

    A specialty with zero professionals staffed against it is a dead end —
    offering it just to have the very next step ("no tengo profesionales
    cargados para esa especialidad") strand the patient. One unfiltered
    `list_professionals()` call here is cheap next to the alternative (one
    `list_professionals(specialty_id=...)` call per specialty in the
    catalog just to find out which are empty).
    """
    professionals = await gateway.list_professionals()
    return {p.specialty_id for p in professionals if p.specialty_id}


async def match_named_professional(gateway: AppointmentGateway, text: str) -> Professional | None:
    """Finds a professional named directly in free text (e.g. "quiero un
    turno con el doctor Carlos Adahenao") — a patient who already knows
    exactly who they want shouldn't have to name a specialty first. Shared
    by this node's own `professional_mention` fallback and `specialties.py`'s
    equivalent free-text matching.
    """
    professionals = await gateway.list_professionals()
    index = _resolve_by_name(text, [professional.full_name for professional in professionals])
    return professionals[index] if index is not None else None


def choose_professional_prompt() -> str:
    """The exact wording this node uses to ask for a professional, so a
    patient handed over from `specialties.py` sees one consistent prompt."""
    return _CHOOSE_PROFESSIONAL_PROMPT


def _merge_identification(
    text: str,
    remembered_full_name: str | None,
    remembered_dni: str | None,
) -> tuple[str | None, str | None]:
    """Merges this turn's free text with whatever the patient already gave
    earlier in this same identification stage. A piece the patient
    addresses this turn always overrides what was remembered — a fresh
    correction should never be shadowed by a stale answer — and a piece
    left untouched this turn falls back to what was already remembered, so
    the patient never has to repeat something they already got right.

    This is only ever called from `STAGE_AWAITING_IDENTIFICATION` (see this
    node's `node()` dispatch) — the bot already asked specifically for
    name+DNI, so any free text arriving here IS an identification attempt
    by construction; there is no ordinary-chatter ambiguity left to guard
    against. A message with no digit run is always read as a bare name
    (bug found live: the old guard discarded a name-first answer entirely
    whenever no DNI was on record yet — e.g. "Pedro Cassera" then
    "30131313" — so by the time the DNI arrived, the name had never been
    remembered and got asked for AGAIN even though the patient already
    typed it).
    """
    full_name, dni = _extract_identification_pieces(text)
    return (
        full_name if full_name is not None else remembered_full_name,
        dni if dni is not None else remembered_dni,
    )


def _format_slot_option(slot: AppointmentSlot, professional_names: dict[str, str]) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    return f"- {professional_name}: {slot.time_range.start.strftime('%A %d/%m %H:%M hs')}"


def _slot_button(slot: AppointmentSlot) -> InteractiveButton:
    return InteractiveButton(
        id=f"{SELECT_SLOT_PAYLOAD_PREFIX}{slot.id}",
        title=slot.time_range.start.strftime("%d/%m %H:%M"),
    )


def _format_appointment_option(appointment: Appointment, professional_names: dict[str, str]) -> str:
    professional_name = professional_names.get(appointment.slot.professional_id, "Profesional")
    start = appointment.slot.time_range.start
    return f"- {professional_name}: {start.strftime('%A %d/%m %H:%M hs')}"


def _appointment_button(appointment: Appointment) -> InteractiveButton:
    return InteractiveButton(
        id=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}{appointment.id}",
        title=appointment.slot.time_range.start.strftime("%d/%m %H:%M"),
    )


def _confirmation_message(slot: AppointmentSlot, professional_names: dict[str, str]) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    return (
        "Tengo disponible:\n\n"
        f"{professional_name}\n"
        f"{slot.time_range.start.strftime('%A %d/%m/%Y')}\n"
        f"{slot.time_range.start.strftime('%H:%M')} hs\n\n"
        "Confirmás que querés reservar este turno?"
    )


def _cancel_confirmation_message(
    appointment: Appointment, professional_names: dict[str, str]
) -> str:
    slot = appointment.slot
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    return (
        "Vas a cancelar este turno:\n\n"
        f"{professional_name}\n"
        f"{slot.time_range.start.strftime('%A %d/%m/%Y')}\n"
        f"{slot.time_range.start.strftime('%H:%M')} hs\n\n"
        "Confirmás que querés cancelarlo?"
    )


def _reschedule_confirmation_message(
    slot: AppointmentSlot, professional_names: dict[str, str]
) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    return (
        "Vas a reagendar tu turno a:\n\n"
        f"{professional_name}\n"
        f"{slot.time_range.start.strftime('%A %d/%m/%Y')}\n"
        f"{slot.time_range.start.strftime('%H:%M')} hs\n\n"
        "Confirmás el cambio?"
    )


def _new_patient_confirmation_message(full_name: str, dni: str) -> str:
    return (
        "No encontramos ningún paciente registrado con esos datos. "
        "Confirmás que querés crear tu ficha con estos datos?\n\n"
        f"Nombre: {full_name}\n"
        f"DNI: {dni}"
    )


def _new_patient_proposal_payload(
    full_name: str, dni: str, phone: PhoneNumber
) -> dict[str, object]:
    return {"full_name": full_name, "dni": dni, "phone": str(phone)}


def _verification_confirmation_message(patient: Patient) -> str:
    return (
        "Encontramos estos datos, ¿son correctos?\n\n"
        f"Nombre: {patient.full_name}\n"
        f"DNI: {patient.dni}"
    )


def _success_message(appointment: Appointment) -> str:
    slot = appointment.slot
    return (
        "✅ Tu turno quedó confirmado.\n\n"
        f"{slot.time_range.start.strftime('%A %d/%m/%Y')}\n"
        f"{slot.time_range.start.strftime('%H:%M')} hs\n\n"
        "Te esperamos en la clínica."
    )


def _reschedule_success_message(appointment: Appointment) -> str:
    slot = appointment.slot
    return (
        "✅ Reagendamos tu turno.\n\n"
        f"{slot.time_range.start.strftime('%A %d/%m/%Y')}\n"
        f"{slot.time_range.start.strftime('%H:%M')} hs\n\n"
        "Te esperamos en la clínica."
    )


def _cancel_success_message() -> str:
    return "✅ Cancelamos tu turno. Si querés coordinar otro, avisame."


def _operation_menu_message(known_patient_name: str | None) -> str:
    """Greets a returning contact by name (this session's brief: "hablarle
    por el nombre"). Text only — `known_patient_name` never changes WHICH
    stage this turn lands in, only what the menu says."""
    if not known_patient_name:
        return _OPERATION_MENU_MESSAGE
    first_name = known_patient_name.strip().split(maxsplit=1)[0]
    return f"¡Hola de nuevo, {first_name}! {_OPERATION_MENU_MESSAGE}"


def _patient_to_primitives(patient: Patient) -> dict[str, object]:
    return {
        "id": patient.id,
        "full_name": patient.full_name,
        "phone": str(patient.phone),
        "dni": patient.dni,
    }


def _patient_from_payload(payload: dict[str, object]) -> Patient:
    dni = payload.get("patient_dni")
    return Patient(
        id=str(payload["patient_id"]),
        full_name=str(payload["patient_full_name"]),
        phone=PhoneNumber(str(payload["patient_phone"])),
        dni=str(dni) if dni is not None else None,
    )


def _slot_from_payload(payload: dict[str, object]) -> AppointmentSlot:
    return AppointmentSlot(
        id=str(payload["slot_id"]),
        professional_id=str(payload["professional_id"]),
        specialty_id=str(payload["specialty_id"]),
        time_range=DateTimeRange(
            datetime.fromisoformat(str(payload["slot_start"])),
            datetime.fromisoformat(str(payload["slot_end"])),
        ),
    )


def _proposal_payload(patient: dict[str, object], slot: AppointmentSlot) -> dict[str, object]:
    return {
        "patient_id": patient["id"],
        "patient_full_name": patient["full_name"],
        "patient_phone": patient["phone"],
        "patient_dni": patient["dni"],
        "slot_id": slot.id,
        "professional_id": slot.professional_id,
        "specialty_id": slot.specialty_id,
        "slot_start": slot.time_range.start.isoformat(),
        "slot_end": slot.time_range.end.isoformat(),
    }


def _reschedule_proposal_payload(appointment_id: str, slot: AppointmentSlot) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "slot_id": slot.id,
        "professional_id": slot.professional_id,
        "specialty_id": slot.specialty_id,
        "slot_start": slot.time_range.start.isoformat(),
        "slot_end": slot.time_range.end.isoformat(),
    }


def _cancel_proposal_payload(appointment: Appointment) -> dict[str, object]:
    return {
        "appointment_id": str(appointment.id),
        "patient_id": appointment.patient_id,
        "professional_id": appointment.slot.professional_id,
        "slot_start": appointment.slot.time_range.start.isoformat(),
        "slot_end": appointment.slot.time_range.end.isoformat(),
    }


def create_appointment_node(
    appointment_gateway: AppointmentGateway,
    patient_gateway: PatientGateway,
    proposal_repositories_provider: ProposalRepositoriesProvider,
    conversation_repository: ConversationRepository,
    redis_client: Redis,
    confirmation_timeout_seconds: int,
    llm_provider: LLMProvider,
    specialty_gateway: SpecialtyGateway,
    agreement_gateway: AgreementGateway,
    verification_flow_id: str = "",
    registration_flow_id: str = "",
) -> AgentNode:
    """Full turno management stage machine — create, reschedule, cancel
    (PRD.md §9-16, §32, §72).

    All three PRD.md §16 operations (`create_appointment`,
    `reschedule_appointment`, `cancel_appointment`) share this one node and
    the same underlying machinery: `ProposeAppointmentUseCase`/
    `ConfirmPendingActionUseCase`/`RejectPendingActionUseCase` are fully
    generic (action_type/payload are caller-supplied), and CANCEL/RESCHEDULE
    both reuse `STAGE_AWAITING_APPOINTMENT_SELECTION` (§13-14's "consultar
    próximas citas -> mostrar citas -> seleccionar cita" is identical for
    both). RESCHEDULE additionally reuses `STAGE_AWAITING_SLOT_SELECTION`
    (its "buscar nueva disponibilidad -> mostrar opciones -> seleccionar
    horario" is identical to CREATE's own slot search). The not-yet-built
    expiry worker (PRD.md §16.3) is a separate, later piece of
    infrastructure; this node only ever leaves the durable state it needs
    behind (a `pending` `PendingAction` + `ScheduledAction`), it never runs
    that worker's logic.

    Stages (`collected_data["stage"]`, this node's own cursor):

    ```
    (no stage)                   -> show the §9 operation menu
    awaiting_operation_selection -> OPERATION_CREATE/RESCHEDULE/CANCEL button
                                     -> ask for identification
    awaiting_identification      -> parse "nombre, dni" -> identify patient
                                     -> CREATE: search availability, show slots
                                     -> RESCHEDULE/CANCEL: list patient's
                                        appointments, show appointment buttons
    awaiting_appointment_selection -> a SELECT_APPOINTMENT:<id> button
                                     -> CANCEL: ProposeAppointmentUseCase
                                        (action_type=cancel_appointment)
                                     -> RESCHEDULE: search new availability,
                                        show slot buttons (-> awaiting_slot_selection)
    awaiting_slot_selection       -> a SELECT_SLOT:<id> button -> ProposeAppointmentUseCase
                                     (action_type=create_appointment or
                                     reschedule_appointment, per collected_data["operation"])
                                     -> show confirm/reject buttons
    awaiting_confirmation         -> CONFIRM_APPOINTMENT / REJECT_APPOINTMENT button
                                     -> ConfirmPendingActionUseCase / RejectPendingActionUseCase
                                     -> (on confirm) branches by the confirmed
                                        PendingAction's own `action_type`
    ```

    Determinism (PRD.md §6, §24.2, §24.4): while any of the four
    button-driven stages above is active, `resolve_interaction` already
    guarantees free text/audio never itself reaches this node with intent
    other than "appointment" (except the global handoff escape hatch) — but
    free text arriving here mid-flow must still never advance the stage on
    its own. This node enforces that itself: a turn with `button_payload is
    None` while one of those stages is active only re-sends the same
    buttons with a reminder, it never interprets the text as a selection or
    a confirmation.

    Reconstruction from `PendingAction.payload`/`.action_type`, not
    `collected_data`: once a proposal exists, both WHICH operation to
    execute and the data it needs are read back from the just-confirmed
    `PendingAction` (`.action_type`, `_patient_from_payload`/
    `_slot_from_payload`) — the durably committed record
    (`ProposeAppointmentUseCase`'s explicit-commit transaction) — rather
    than trusted from `collected_data`'s checkpointer round-trip.
    `collected_data["operation"]` (the same three `action_type` tokens)
    only drives the PRE-proposal turns, where no durable record exists yet
    to read from instead. `collected_data` otherwise only ever holds a
    convenience copy for the CURRENT still-open selection window (offering
    slots/appointments again, re-showing the same options on a stray text
    message).

    PRD.md §72 — never informs success without a real Dentalink response:
    the success message is only ever built from `RevalidateAndCreateAppointmentUseCase`'s
    return value, never assumed after `ConfirmPendingActionUseCase` alone.
    """
    search_availability = SearchAvailabilityUseCase(appointment_gateway)
    identify_patient = IdentifyPatientUseCase(patient_gateway)
    get_patient_appointments = GetPatientAppointmentsUseCase(appointment_gateway)
    propose_appointment = ProposeAppointmentUseCase(
        proposal_repositories_provider,
        confirmation_timeout_seconds=confirmation_timeout_seconds,
    )
    revalidate_and_create = RevalidateAndCreateAppointmentUseCase(appointment_gateway, redis_client)
    revalidate_and_reschedule = RevalidateAndRescheduleAppointmentUseCase(
        appointment_gateway, redis_client
    )
    cancel_appointment = CancelAppointmentUseCase(appointment_gateway)
    set_conversation_input_state = SetConversationInputStateUseCase(conversation_repository)
    rotate_workflow_session = RotateWorkflowSessionUseCase(conversation_repository)
    list_specialties = ListSpecialtiesUseCase(specialty_gateway)

    async def _ask_identification_message(
        conversation_id: ConversationId,
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> str:
        """Varied wording for the very first identification prompt — three
        different entry points (post-slot, reschedule, cancel) all reach
        this same ask, and a patient bouncing between them shouldn't see
        the identical canned sentence every time."""
        return await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "ask_identification",
            {
                "situacion": (
                    "Hay que identificar al paciente antes de seguir: pedile su nombre "
                    "completo y su DNI."
                ),
                "formato_requerido": (
                    "Nombre y apellido completos, y DNI (7 u 8 dígitos), en uno o dos "
                    "mensajes, ejemplo: Rosa Gómez, 30123456. Incluí ese ejemplo en tu "
                    "respuesta."
                ),
            },
            _ASK_IDENTIFICATION_MESSAGE,
            recent_messages,
            contact_memory,
        )

    async def _begin_identification(
        conversation_id: ConversationId,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        """Starts identification — sends the verification Flow when one is
        configured (`verification_flow_id`), else falls back to the
        original free-text ask. The three entry points that used to call
        `_ask_identification_message` directly (post-slot, reschedule,
        cancel) all start here now, so the Flow rollout is a single
        on/off switch rather than three places to keep in sync.
        """
        if verification_flow_id:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            intro = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "send_verification_flow",
                {
                    "situacion": (
                        "Hay que identificar al paciente antes de seguir — le vamos a "
                        "mandar un formulario corto para que confirme nombre y DNI."
                    ),
                },
                _SEND_VERIFICATION_FLOW_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": intro,
                "response_buttons": None,
                "response_flow": FlowRequest(
                    flow_id=verification_flow_id,
                    flow_screen_id=VERIFICATION_FLOW_SCREEN_ID,
                    flow_cta="Verificar",
                    flow_token=str(conversation_id),
                ),
                "requires_handoff": False,
                "collected_data": {**collected_data, "stage": STAGE_AWAITING_VERIFICATION_FLOW},
            }
        return {
            "response_text": await _ask_identification_message(
                conversation_id, recent_messages, contact_memory
            ),
            "response_buttons": None,
            "requires_handoff": False,
            "collected_data": {**collected_data, "stage": STAGE_AWAITING_IDENTIFICATION},
        }

    async def _begin_registration(
        conversation_id: ConversationId,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        """Sends the registration Flow — reached when verification found no
        match for the patient, or they rejected the found data as not
        theirs. Requires `registration_flow_id` to be configured; callers
        only ever reach here after `verification_flow_id` already sent a
        Flow successfully, so both are expected to be configured together.
        """
        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        intro = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "send_registration_flow",
            {
                "situacion": (
                    "No encontramos al paciente registrado — hay que pedirle que "
                    "complete sus datos con un formulario."
                ),
            },
            _SEND_REGISTRATION_FLOW_MESSAGE,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": intro,
            "response_buttons": None,
            "response_flow": FlowRequest(
                flow_id=registration_flow_id,
                flow_screen_id=REGISTRATION_FLOW_SCREEN_ID,
                flow_cta="Completar",
                flow_token=str(conversation_id),
            ),
            "requires_handoff": False,
            "collected_data": {**collected_data, "stage": STAGE_AWAITING_REGISTRATION_FLOW},
        }

    async def _cancel_follow_up(repositories: ProposalRepositories, pending_action_id: str) -> None:
        scheduled_actions = repositories.scheduled_actions
        scheduled_action = await scheduled_actions.get_by_pending_action_id(pending_action_id)
        if scheduled_action is not None:
            await scheduled_actions.transition_status(
                scheduled_action.id, from_status="scheduled", to_status="cancelled"
            )

    async def _offer_specialties(
        conversation_id: ConversationId, collected_data: dict[str, object]
    ) -> dict[str, object]:
        specialties = await list_specialties.execute()
        staffed = await staffed_specialty_ids(appointment_gateway)
        specialties = [s for s in specialties if s.id in staffed]
        if not specialties:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": _NO_SPECIALTIES_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": _fresh_tramite(),
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = cast(int, collected_data.get("specialties_page", 0) or 0)
        return {
            "response_text": _CHOOSE_SPECIALTY_PROMPT,
            "response_buttons": None,
            "response_list": specialties_list_message(
                specialties, page=page, include_back=True
            ),
            "requires_handoff": False,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": specialties,
                "specialties_page": page,
            },
        }

    async def _offer_professionals(
        conversation_id: ConversationId,
        specialty_id: str,
        specialty_name: str,
        collected_data: dict[str, object],
    ) -> dict[str, object]:
        professionals = await appointment_gateway.list_professionals(specialty_id=specialty_id)
        if not professionals:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": _NO_PROFESSIONALS_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": _fresh_tramite(),
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = cast(int, collected_data.get("doctors_page", 0) or 0)
        return {
            "response_text": _CHOOSE_PROFESSIONAL_PROMPT,
            "response_buttons": None,
            "response_list": professionals_list_message(
                professionals, page=page, include_back=True
            ),
            "requires_handoff": False,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "chosen_specialty_id": specialty_id,
                "chosen_specialty_name": specialty_name,
                "professional_options": professionals,
                "doctors_page": page,
            },
        }

    async def _offer_slots(
        conversation_id: ConversationId,
        patient: dict[str, object] | None,
        collected_data: dict[str, object],
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        # `specialty_id` is deliberately never forwarded: Dentalink's
        # `/v5/agendas` does not return `id_especialidad`, so filtering on
        # it would discard every real slot. The specialty is honoured one
        # step earlier, by only offering professionals who teach it.
        slots = await search_availability.execute(
            specialty_id=None,
            professional_id=cast(str | None, collected_data.get("chosen_professional_id")),
            date_range=DateTimeRange(now, now + _SEARCH_WINDOW),
            # Only this many are ever shown, and each extra day searched is
            # another Dentalink request — see the port's own docstring.
            limit=_MAX_OPTIONS_SHOWN,
        )
        if not slots:
            await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
            return {
                "response_text": _NO_SLOTS_MESSAGE,
                "response_buttons": _NO_AVAILABILITY_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": None,
<<<<<<< Updated upstream
                "collected_data": {
                    **collected_data,
                    "stage": STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
                },
=======
                "collected_data": _fresh_tramite(),
>>>>>>> Stashed changes
            }

        options = slots[:_MAX_OPTIONS_SHOWN]
        professionals = await appointment_gateway.list_professionals()
        professional_names = {
            professional.id: professional.full_name for professional in professionals
        }
        lines = "\n".join(_format_slot_option(slot, professional_names) for slot in options)
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        return {
            "response_text": f"{_CHOOSE_SLOT_PROMPT}\n\n{lines}",
            "response_buttons": [_slot_button(slot) for slot in options],
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_SLOT_SELECTION,
                # Never let an explicit `None` here (the CREATE flow's own
                # "not identified yet" state) erase a patient RESCHEDULE
                # already identified earlier in `collected_data`.
                "patient": patient if patient is not None else collected_data.get("patient"),
                "available_slots": options,
                "professional_names": professional_names,
            },
        }

    async def _propose_selected_slot(
        conversation_id: ConversationId,
        patient: dict[str, object],
        collected_data: dict[str, object],
    ) -> dict[str, object]:
        """Proposes the slot the patient already picked, now that we know
        who they are — never re-searches availability."""
        selected = cast(AppointmentSlot | None, collected_data.get("pending_selected_slot"))
        if selected is None:
            return {
                "response_text": _SESSION_LOST_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": _fresh_tramite(),
            }

        chosen_specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
        if chosen_specialty_id:
            # Dentalink's `/v5/agendas` never returns `id_especialidad`,
            # so a real slot always arrives with an empty `specialty_id` —
            # yet `create_appointment` sends that field on to Dentalink.
            # The specialty the patient chose at the start of this flow is
            # the only place it can come from.
            selected = replace(selected, specialty_id=chosen_specialty_id)

        professional_names = cast(dict[str, str], collected_data.get("professional_names", {}))
        pending_action = await propose_appointment.execute(
            conversation_id, CREATE_APPOINTMENT_ACTION, _proposal_payload(patient, selected)
        )
        await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
        return {
            "response_text": _confirmation_message(selected, professional_names),
            "response_buttons": _CONFIRM_BUTTONS,
            "requires_handoff": False,
            "pending_action_id": pending_action.id,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_CONFIRMATION,
                "patient": patient,
                "pending_selected_slot": selected,
            },
        }

    async def _offer_appointments(
        conversation_id: ConversationId,
        patient: dict[str, object],
        patient_id: str,
        collected_data: dict[str, object],
    ) -> dict[str, object]:
        appointments = await get_patient_appointments.execute(patient_id)
        if not appointments:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": _NO_APPOINTMENTS_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": _fresh_tramite(),
            }

        professionals = await appointment_gateway.list_professionals()
        professional_names = {
            professional.id: professional.full_name for professional in professionals
        }
        lines = "\n".join(
            _format_appointment_option(appointment, professional_names)
            for appointment in appointments
        )
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        return {
            "response_text": f"{_CHOOSE_APPOINTMENT_PROMPT}\n\n{lines}",
            "response_buttons": [_appointment_button(appointment) for appointment in appointments],
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_APPOINTMENT_SELECTION,
                "patient": patient,
                "patient_appointments": appointments,
                "professional_names": professional_names,
            },
        }

    async def node(state: AgentState) -> dict[str, object]:
        conversation_id = ConversationId(state["conversation_id"])
        workflow_conversation = await conversation_repository.get_by_id(conversation_id)
        workflow_generation = (
            workflow_conversation.workflow_session_generation
            if workflow_conversation is not None
            else 1
        )
        collected_data = state["collected_data"]
        stage = collected_data.get("stage")

        if state["button_payload"] == MENU_MAIN_PAYLOAD:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": WELCOME_TEXT,
                "response_buttons": None,
                "response_list": WELCOME_LIST,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {},
            }

        returned_to_main_menu = False
        if stage is not None and state["button_payload"] in _MAIN_MENU_PAYLOADS:
            # A main-menu tap is an unambiguous "start over", never an
            # answer to whatever question is currently on screen. Seen
            # live: a patient trapped mid-identification tapped "Turnos"
            # and the agent went right on asking for their DNI. Every
            # per-stage counter is dropped with the stage, so an abandoned
            # flow's retry history never follows them into the next one.
            collected_data = _fresh_tramite()
            stage = None
            returned_to_main_menu = True

        if stage == STAGE_AWAITING_CONFIRMATION:
            pending_action_id = state.get("pending_action_id")
            button_payload = state["button_payload"]

            if button_payload is None or pending_action_id is None:
                return {
                    "response_text": _CONFIRMATION_REMINDER,
                    "response_buttons": _CONFIRM_BUTTONS,
                    "requires_handoff": False,
                }

            if button_payload == REJECT_APPOINTMENT_PAYLOAD:
                async with proposal_repositories_provider() as repositories:
                    try:
                        await RejectPendingActionUseCase(repositories.pending_actions).execute(
                            pending_action_id
                        )
                    except (InvalidConfirmationError, PendingActionExpiredError):
                        pass
                    else:
                        await _cancel_follow_up(repositories, pending_action_id)
                await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": _PROPOSAL_REJECTED_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "pending_action_id": None,
                    "collected_data": _fresh_tramite(),
                }

            if button_payload == CONFIRM_APPOINTMENT_PAYLOAD:
                confirm_error: Exception | None = None
                confirmed_payload: dict[str, object] | None = None
                confirmed_action_type: str | None = None
                async with proposal_repositories_provider() as repositories:
                    try:
                        confirmed = await ConfirmPendingActionUseCase(
                            repositories.pending_actions
                        ).execute(pending_action_id)
                    except (InvalidConfirmationError, PendingActionExpiredError) as exc:
                        confirm_error = exc
                    else:
                        confirmed_payload = confirmed.payload
                        confirmed_action_type = confirmed.action_type
                        await _cancel_follow_up(repositories, pending_action_id)

                if isinstance(confirm_error, InvalidConfirmationError):
                    return {
                        "response_text": _PROPOSAL_NOT_FOUND_MESSAGE,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": _fresh_tramite(),
                    }
                if isinstance(confirm_error, PendingActionExpiredError):
                    patient = cast(dict[str, object] | None, collected_data.get("patient"))
                    if patient is None:
                        return {
                            "response_text": _SESSION_LOST_MESSAGE,
                            "response_buttons": None,
                            "requires_handoff": False,
                            "pending_action_id": None,
                            "collected_data": _fresh_tramite(),
                        }
                    offer = await _offer_slots(conversation_id, patient, collected_data)
                    offer["response_text"] = (
                        f"{_PROPOSAL_NO_LONGER_VALID_MESSAGE}\n\n{offer['response_text']}"
                    )
                    return offer

                if confirmed_payload is None:  # pragma: no cover - impossible by construction
                    raise AssertionError("confirm succeeded without a payload")

                if confirmed_action_type == CANCEL_APPOINTMENT_ACTION:
                    appointment_id = str(confirmed_payload["appointment_id"])
                    idempotency_key = f"cancel:{conversation_id}:{pending_action_id}"
                    await cancel_appointment.execute(appointment_id, idempotency_key)
                    await rotate_workflow_session.execute(
                        conversation_id, expected_generation=workflow_generation
                    )
                    return {
                        "response_text": _cancel_success_message(),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": _fresh_tramite(),
                    }

                if confirmed_action_type == CREATE_APPOINTMENT_ACTION:
                    patient_entity = _patient_from_payload(confirmed_payload)
                    slot = _slot_from_payload(confirmed_payload)
                    idempotency_key = f"create:{conversation_id}:{pending_action_id}"
                    try:
                        appointment = await revalidate_and_create.execute(
                            patient_entity, slot, idempotency_key
                        )
                    except AppointmentSlotUnavailableError:
                        offer = await _offer_slots(
                            conversation_id, _patient_to_primitives(patient_entity), collected_data
                        )
                        offer["response_text"] = (
                            f"{_SLOT_TAKEN_MESSAGE}\n\n{offer['response_text']}"
                        )
                        return offer

                    await rotate_workflow_session.execute(
                        conversation_id, expected_generation=workflow_generation
                    )
                    return {
                        "response_text": _success_message(appointment),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": _fresh_tramite(),
                    }

                if confirmed_action_type == CREATE_PATIENT_ACTION:
                    full_name = str(confirmed_payload["full_name"])
                    dni = str(confirmed_payload["dni"])
                    phone = PhoneNumber(str(confirmed_payload["phone"]))
                    try:
                        new_patient = await patient_gateway.create_patient(full_name, dni, phone)
                    except PatientAlreadyExistsError:
                        # Race: someone else created a matching-DNI record
                        # between propose and confirm. Re-look-up by the
                        # same name+DNI the patient just confirmed rather
                        # than failing the turn.
                        recovered = await identify_patient.execute(full_name, dni)
                        if recovered is None:
                            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                            # The message asks the patient to retype their
                            # name+DNI — stay in STAGE_AWAITING_IDENTIFICATION
                            # so that reply is actually parsed as the retry
                            # it was asked for, instead of falling out of
                            # the flow entirely (losing the slot they'd
                            # already picked) and landing in generic intent
                            # classification. Both remembered pieces are
                            # cleared: the name+DNI just confirmed are the
                            # ones that turned out not to match, so keeping
                            # either around could resurrect the same bad
                            # pair instead of forcing a genuinely fresh one.
                            text = await generate_or_fallback(
                                llm_provider,
                                str(conversation_id),
                                "identification_name_mismatch",
                                {
                                    "situacion": (
                                        "Encontramos un paciente con ese DNI, pero registrado "
                                        "con otro nombre. Por seguridad hay que pedirle que "
                                        "vuelva a escribir nombre y DNI completos."
                                    ),
                                },
                                _NEW_PATIENT_RACE_LOST_MESSAGE,
                                state["recent_messages"],
                                state["contact_memory_summary"],
                            )
                            return {
                                "response_text": text,
                                "response_buttons": None,
                                "requires_handoff": False,
                                "pending_action_id": None,
<<<<<<< Updated upstream
                                "collected_data": {
                                    **collected_data,
                                    "stage": STAGE_AWAITING_IDENTIFICATION,
                                    "identification_full_name": None,
                                    "identification_dni": None,
                                },
=======
                                "collected_data": _fresh_tramite(),
>>>>>>> Stashed changes
                            }
                        new_patient = recovered

                    if collected_data.get("pending_selected_slot") is None:
                        # Registration reached from reschedule/cancel: there
                        # is no slot to propose, and a patient created one
                        # second ago has nothing to reschedule. Booking is
                        # the only thing left that helps them.
                        return await _offer_specialties(
                            conversation_id,
                            {
                                **collected_data,
                                "operation": CREATE_APPOINTMENT_ACTION,
                                "patient": _patient_to_primitives(new_patient),
                            },
                        )
                    # The patient already picked their slot before
                    # identifying, so continue with that exact slot — never
                    # re-search.
                    return await _propose_selected_slot(
                        conversation_id, _patient_to_primitives(new_patient), collected_data
                    )

                if confirmed_action_type == RESCHEDULE_APPOINTMENT_ACTION:
                    appointment_id = str(confirmed_payload["appointment_id"])
                    new_slot = _slot_from_payload(confirmed_payload)
                    idempotency_key = f"reschedule:{conversation_id}:{pending_action_id}"
                    try:
                        rescheduled = await revalidate_and_reschedule.execute(
                            appointment_id, new_slot, idempotency_key
                        )
                    except AppointmentSlotUnavailableError:
                        patient = cast(dict[str, object] | None, collected_data.get("patient"))
                        if patient is None:
                            return {
                                "response_text": _SESSION_LOST_MESSAGE,
                                "response_buttons": None,
                                "requires_handoff": False,
                                "pending_action_id": None,
                                "collected_data": _fresh_tramite(),
                            }
                        offer = await _offer_slots(conversation_id, patient, collected_data)
                        offer["response_text"] = (
                            f"{_SLOT_TAKEN_MESSAGE}\n\n{offer['response_text']}"
                        )
                        return offer

                    await rotate_workflow_session.execute(
                        conversation_id, expected_generation=workflow_generation
                    )
                    return {
                        "response_text": _reschedule_success_message(rescheduled),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": _fresh_tramite(),
                    }

                raise AssertionError(  # pragma: no cover - impossible by construction
                    f"unsupported action_type: {confirmed_action_type}"
                )

            # An unrecognized/stale button while awaiting confirmation.
            return {
                "response_text": _CONFIRMATION_REMINDER,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_SLOT_SELECTION:
            button_payload = state["button_payload"]
            available_slots = cast(list[AppointmentSlot], collected_data.get("available_slots", []))
            patient = cast(dict[str, object] | None, collected_data.get("patient"))
            # In the CREATE flow the patient is not identified yet at this
            # point (that now happens after picking a slot), so only the
            # RESCHEDULE flow requires one here.
            rescheduling = collected_data.get("rescheduling_appointment_id") is not None

            if not available_slots or (rescheduling and patient is None):
                return {
                    "response_text": _SESSION_LOST_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": _fresh_tramite(),
                }

            if button_payload is None or not button_payload.startswith(SELECT_SLOT_PAYLOAD_PREFIX):
                message = (
                    _SLOT_SELECTION_REMINDER
                    if button_payload is None
                    else _STALE_SLOT_SELECTION_MESSAGE
                )
                professional_names = cast(
                    dict[str, str], collected_data.get("professional_names", {})
                )
                lines = "\n".join(
                    _format_slot_option(slot, professional_names) for slot in available_slots
                )
                return {
                    "response_text": f"{message}\n\n{lines}",
                    "response_buttons": [_slot_button(slot) for slot in available_slots],
                    "requires_handoff": False,
                }

            slot_id = button_payload[len(SELECT_SLOT_PAYLOAD_PREFIX) :]
            selected = next((slot for slot in available_slots if slot.id == slot_id), None)
            if selected is None:
                professional_names = cast(
                    dict[str, str], collected_data.get("professional_names", {})
                )
                lines = "\n".join(
                    _format_slot_option(slot, professional_names) for slot in available_slots
                )
                return {
                    "response_text": f"{_STALE_SLOT_SELECTION_MESSAGE}\n\n{lines}",
                    "response_buttons": [_slot_button(slot) for slot in available_slots],
                    "requires_handoff": False,
                }

            professional_names = cast(dict[str, str], collected_data.get("professional_names", {}))
            rescheduling_appointment_id = cast(
                str | None, collected_data.get("rescheduling_appointment_id")
            )
            if rescheduling_appointment_id is None:
                # CREATE flow: the patient has now seen a real slot, so
                # this is the moment to ask who they are — the reordering
                # this session's brief asked for. The chosen slot is
                # carried forward so identification never re-searches.
                return await _begin_identification(
                    conversation_id,
                    {**collected_data, "pending_selected_slot": selected},
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )

            pending_action = await propose_appointment.execute(
                conversation_id,
                RESCHEDULE_APPOINTMENT_ACTION,
                _reschedule_proposal_payload(rescheduling_appointment_id, selected),
            )
            confirmation_text = _reschedule_confirmation_message(selected, professional_names)

            await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
            return {
                "response_text": confirmation_text,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": pending_action.id,
                "collected_data": {**collected_data, "stage": STAGE_AWAITING_CONFIRMATION},
            }

        if stage == STAGE_AWAITING_APPOINTMENT_SELECTION:
            button_payload = state["button_payload"]
            patient_appointments = cast(
                list[Appointment], collected_data.get("patient_appointments", [])
            )
            patient = cast(dict[str, object] | None, collected_data.get("patient"))
            operation = collected_data.get("operation")

            if not patient_appointments or patient is None:
                return {
                    "response_text": _SESSION_LOST_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": _fresh_tramite(),
                }

            if button_payload is None or not button_payload.startswith(
                SELECT_APPOINTMENT_PAYLOAD_PREFIX
            ):
                message = (
                    _APPOINTMENT_SELECTION_REMINDER
                    if button_payload is None
                    else _STALE_APPOINTMENT_SELECTION_MESSAGE
                )
                professional_names = cast(
                    dict[str, str], collected_data.get("professional_names", {})
                )
                lines = "\n".join(
                    _format_appointment_option(appointment, professional_names)
                    for appointment in patient_appointments
                )
                return {
                    "response_text": f"{message}\n\n{lines}",
                    "response_buttons": [
                        _appointment_button(appointment) for appointment in patient_appointments
                    ],
                    "requires_handoff": False,
                }

            selected_appointment_id = button_payload[len(SELECT_APPOINTMENT_PAYLOAD_PREFIX) :]
            selected_appointment = next(
                (a for a in patient_appointments if str(a.id) == selected_appointment_id), None
            )
            professional_names = cast(dict[str, str], collected_data.get("professional_names", {}))
            if selected_appointment is None:
                lines = "\n".join(
                    _format_appointment_option(appointment, professional_names)
                    for appointment in patient_appointments
                )
                return {
                    "response_text": f"{_STALE_APPOINTMENT_SELECTION_MESSAGE}\n\n{lines}",
                    "response_buttons": [
                        _appointment_button(appointment) for appointment in patient_appointments
                    ],
                    "requires_handoff": False,
                }

            if operation == CANCEL_APPOINTMENT_ACTION:
                pending_action = await propose_appointment.execute(
                    conversation_id,
                    CANCEL_APPOINTMENT_ACTION,
                    _cancel_proposal_payload(selected_appointment),
                )
                await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
                return {
                    "response_text": _cancel_confirmation_message(
                        selected_appointment, professional_names
                    ),
                    "response_buttons": _CONFIRM_BUTTONS,
                    "requires_handoff": False,
                    "pending_action_id": pending_action.id,
                    "collected_data": {**collected_data, "stage": STAGE_AWAITING_CONFIRMATION},
                }

            if operation == RESCHEDULE_APPOINTMENT_ACTION:
                rescheduling_professional_id = selected_appointment.slot.professional_id
                professional_name = professional_names.get(
                    rescheduling_professional_id, "tu profesional actual"
                )
                await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
                return {
                    "response_text": (
                        f"Tu turno es con {professional_name}. ¿Querés mantener el mismo "
                        "profesional o elegir otro?"
                    ),
                    "response_buttons": _RESCHEDULE_PROFESSIONAL_CHOICE_BUTTONS,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "stage": STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE,
                        "rescheduling_appointment_id": str(selected_appointment.id),
                        "rescheduling_professional_id": rescheduling_professional_id,
                    },
                }

            raise AssertionError(  # pragma: no cover - impossible by construction
                f"unsupported operation: {operation}"
            )

        if stage == STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE:
            button_payload = state["button_payload"]
            rescheduling_professional_id = cast(
                str, collected_data.get("rescheduling_professional_id", "")
            )
            patient = cast(dict[str, object] | None, collected_data.get("patient"))
            if button_payload in (
                RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD,
                RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD,
            ):
                professionals = await appointment_gateway.list_professionals()
                current = next(
                    (p for p in professionals if p.id == rescheduling_professional_id), None
                )
                specialty_id = current.specialty_id if current is not None else None
                specialty_name = "esa especialidad"
                if current is not None:
                    specialties = await list_specialties.execute()
                    specialty_name = next(
                        (s.name for s in specialties if s.id == current.specialty_id),
                        specialty_name,
                    )
                if button_payload == RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD and specialty_id:
                    return await _offer_professionals(
                        conversation_id, specialty_id, specialty_name, collected_data
                    )
                extra: dict[str, object] = {"chosen_professional_id": rescheduling_professional_id}
                if specialty_id:
                    extra["chosen_specialty_id"] = specialty_id
                    extra["chosen_specialty_name"] = specialty_name
                return await _offer_slots(conversation_id, patient, {**collected_data, **extra})
            return {
                "response_text": _RESCHEDULE_PROFESSIONAL_CHOICE_REMINDER,
                "response_buttons": _RESCHEDULE_PROFESSIONAL_CHOICE_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_NO_SLOTS_CHOICE:
            if state["button_payload"] == _VIEW_OTHER_PROFESSIONALS_PAYLOAD:
                no_slots_specialty_id = cast(str, collected_data.get("chosen_specialty_id", ""))
                no_slots_specialty_name = cast(str, collected_data.get("chosen_specialty_name", ""))
                return await _offer_professionals(
                    conversation_id, no_slots_specialty_id, no_slots_specialty_name, collected_data
                )
            return {
                "response_text": _NO_SLOTS_OTHER_PROFESSIONALS_MESSAGE,
                "response_buttons": _NO_SLOTS_CHOICE_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_VERIFICATION_FLOW:
            flow_fields = parse_flow_response_payload(state["button_payload"])
            if flow_fields is None:
                # The patient typed something instead of using the Flow —
                # it's still open on their screen, so remind them rather
                # than falling back to guessing from free text.
                return {
                    "response_text": _FLOW_REMINDER_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                }
            full_name = str(flow_fields.get("full_name") or "").strip()
            raw_dni = str(flow_fields.get("dni") or "").strip()
            try:
                validated_dni = Dni(raw_dni)
            except ValueError:
                # The Flow's own required/number-only fields should have
                # caught this, but if they somehow didn't, re-sending the
                # same Flow is safer than getting stuck on bad data.
                return await _begin_identification(
                    conversation_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            identified_patient = await identify_patient.execute(full_name, validated_dni.value)
            if identified_patient is None:
                return await _begin_registration(
                    conversation_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
            return {
                "response_text": _verification_confirmation_message(identified_patient),
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
                "collected_data": {
                    **collected_data,
                    "stage": STAGE_AWAITING_VERIFICATION_CONFIRMATION,
                    "patient": _patient_to_primitives(identified_patient),
                    "verified_patient_id": identified_patient.id,
                },
            }

        if stage == STAGE_AWAITING_VERIFICATION_CONFIRMATION:
            button_payload = state["button_payload"]
            if button_payload == CONFIRM_APPOINTMENT_PAYLOAD:
                patient_primitives = cast(dict[str, object], collected_data.get("patient", {}))
                patient_id = cast(str, collected_data.get("verified_patient_id", ""))
                if collected_data.get("operation") == CREATE_APPOINTMENT_ACTION:
                    return await _propose_selected_slot(
                        conversation_id, patient_primitives, collected_data
                    )
                return await _offer_appointments(
                    conversation_id, patient_primitives, patient_id, collected_data
                )
            if button_payload == REJECT_APPOINTMENT_PAYLOAD:
                # "That's not me" — the found record isn't whoever is
                # messaging; collect fresh data instead of risking someone
                # else's identity.
                return await _begin_registration(
                    conversation_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            return {
                "response_text": _CONFIRMATION_REMINDER,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_REGISTRATION_FLOW:
            flow_fields = parse_flow_response_payload(state["button_payload"])
            if flow_fields is None:
                return {
                    "response_text": _FLOW_REMINDER_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                }
            full_name = str(flow_fields.get("full_name") or "").strip()
            raw_dni = str(flow_fields.get("dni") or "").strip()
            email = str(flow_fields.get("email") or "").strip() or None
            obra_social_name = str(flow_fields.get("obra_social") or "").strip()
            try:
                validated_dni = Dni(raw_dni)
            except ValueError:
                return await _begin_registration(
                    conversation_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            contact_phone = PhoneNumber(str(conversation_id).removeprefix("ycloud-"))
            try:
                new_patient = await patient_gateway.create_patient(
                    full_name, validated_dni.value, contact_phone, email=email
                )
            except PatientAlreadyExistsError:
                # Race: someone else registered this exact DNI between the
                # verification check and this submission — look them up
                # instead of failing the turn.
                recovered = await identify_patient.execute(full_name, validated_dni.value)
                if recovered is None:
                    return await _begin_registration(
                        conversation_id,
                        collected_data,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                new_patient = recovered
            if obra_social_name:
                agreement = await agreement_gateway.find_agreement_by_name(obra_social_name)
                if agreement is not None:
                    await agreement_gateway.link_patient_agreement(new_patient.id, agreement.id)
            patient_primitives = _patient_to_primitives(new_patient)
            if collected_data.get("operation") == CREATE_APPOINTMENT_ACTION:
                return await _propose_selected_slot(
                    conversation_id, patient_primitives, collected_data
                )
            return await _offer_appointments(
                conversation_id, patient_primitives, new_patient.id, collected_data
            )

        if stage == STAGE_AWAITING_IDENTIFICATION:
            remembered_full_name = cast(str | None, collected_data.get("identification_full_name"))
            remembered_dni = cast(str | None, collected_data.get("identification_dni"))
            merged_full_name, merged_dni = _merge_identification(
                state["user_message"], remembered_full_name, remembered_dni
            )
            if merged_full_name is None and merged_dni is None:
                retry_count = cast(int, collected_data.get("identification_retry_count", 0)) + 1
                escalating = retry_count > _ESCALATE_IDENTIFICATION_AFTER_ATTEMPTS
                context: dict[str, object] = {
                    "situacion": (
                        "Todavía falta el nombre completo o el DNI para poder buscar al "
                        "paciente en el sistema."
                    ),
                    "formato_requerido": (
                        "Nombre completo y DNI, en un mismo mensaje o en dos, ejemplo: "
                        "Rosa Gómez, 30123456. Incluí ese ejemplo en tu respuesta."
                    ),
                    # The model used to be told WE had failed ("no pudimos
                    # identificar", "no llegué a registrar bien tus datos"),
                    # and it dutifully apologised for a broken system on
                    # every turn. State what is still missing instead.
                    "tono": (
                        "Cordial y breve. No te disculpes ni digas que fallaste o que "
                        "perdiste los datos: simplemente pedí lo que falta."
                    ),
                    "intentos_seguidos": retry_count,
                }
                if escalating:
                    context["instruccion_extra"] = (
                        "Ofrecele además pasarlo con administración, sin insistir."
                    )
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "identification_retry",
                    context,
                    _IDENTIFICATION_NOT_UNDERSTOOD_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                if escalating:
                    await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": text,
                    "response_buttons": _IDENTIFICATION_ESCAPE_BUTTONS if escalating else None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_retry_count": retry_count,
                    },
                }
            if merged_full_name is not None and len(merged_full_name.split()) < 2:
                # A single token ("cassera") looked syntactically fine to
                # the extractor but isn't a full name — matching it against
                # Dentalink by name+DNI fails even for a real, already-
                # registered patient, and from there this flow cascades
                # into "no lo encontramos" -> offering to create a
                # duplicate record for someone who already exists. Catch it
                # before any lookup runs, not after it misfires. Whatever
                # DNI came with it (or was already remembered) is kept —
                # only the name needs fixing.
                retry_count = cast(int, collected_data.get("identification_retry_count", 0)) + 1
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "full_name_incomplete",
                    {
                        "situacion": (
                            "El nombre del paciente parece incompleto "
                            "(una sola palabra, falta nombre o apellido)."
                        ),
                        "nombre_recibido": merged_full_name.strip(),
                        "formato_requerido": (
                            "Nombre Y apellido completos, ejemplo: Rosa Gómez. "
                            "Incluí ese ejemplo en tu respuesta."
                        ),
                        "intentos_seguidos": retry_count,
                    },
                    _NAME_INCOMPLETE_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_retry_count": retry_count,
                        "identification_dni": merged_dni,
                    },
                }
            if merged_full_name is None:
                # DNI in hand, still no usable name — ask for just that
                # instead of repeating the whole "nombre y DNI" prompt
                # (PRD.md never demanded a single message, and the patient
                # already got half of this right).
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "identification_missing_name",
                    {
                        "situacion": "El paciente ya dio su DNI, todavía falta el nombre completo.",
                        "formato_requerido": "Nombre y apellido completos, ejemplo: Rosa Gómez.",
                    },
                    _ASK_NAME_ONLY_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "identification_dni": merged_dni},
                }
            if merged_dni is None:
                # Full name in hand, still no DNI — same idea, ask for just
                # what's missing.
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "identification_missing_dni",
                    {
                        "situacion": "El paciente ya dio su nombre completo, todavía falta el DNI.",
                        "formato_requerido": "Solo números, 7 u 8 dígitos, ejemplo: 30123456.",
                    },
                    _ASK_DNI_ONLY_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_full_name": merged_full_name.strip(),
                    },
                }
            # Both pieces are confirmed non-`None` past this point — the
            # three branches above return early for every other case.
            full_name, dni = merged_full_name, merged_dni
            try:
                validated_dni = Dni(dni)
            except ValueError:
                # Malformed DNI (wrong length, non-digits) — ask again for
                # just the DNI rather than falling through to "not found",
                # and stay in this same stage (no PendingAction needed for
                # a plain format retry).
                retry_count = cast(int, collected_data.get("identification_retry_count", 0)) + 1
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "dni_invalid",
                    {
                        "situacion": (
                            "El paciente escribió un DNI con formato inválido (debe tener "
                            "7 u 8 dígitos, solo números)."
                        ),
                        "dni_recibido": dni,
                        "formato_requerido": (
                            "Solo números, 7 u 8 dígitos, ejemplo: 30123456. Incluí ese "
                            "ejemplo en tu respuesta."
                        ),
                        "intentos_seguidos": retry_count,
                    },
                    _DNI_FORMAT_INVALID_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_retry_count": retry_count,
                        "identification_full_name": full_name.strip(),
                        # Don't remember a DNI that just failed format
                        # validation — a later name-only reply must not
                        # resurrect it as if it had been fine.
                        "identification_dni": None,
                    },
                }
            identified_patient = await identify_patient.execute(full_name, validated_dni.value)
            if identified_patient is None:
                # Offered WHATEVER they came to do, not just for CREATE.
                # Gating this on `operation == CREATE` produced the worst
                # bug this flow has had: a patient who opened with "voy a
                # llegar más tarde" (read as rescheduling) hit a branch
                # that returned no `collected_data` at all, so the stage
                # stayed on identification and every later message came
                # back through the same reprompt — a loop with no exit.
                # Someone Dentalink has never seen has no appointment to
                # reschedule or cancel either, so registering them is the
                # only move that leads anywhere from here.
                #
                # DNI is well-formed but Dentalink has no matching record —
                # propose creating a new patient rather than dead-ending.
                # `phone` comes from this WhatsApp contact's own identity
                # (`conversation_id` is `ycloud-{phone}` by construction,
                # see `IngestMessageUseCase`), never from parsed free text —
                # the created record is always provably tied to whoever is
                # actually messaging.
                contact_phone = PhoneNumber(str(conversation_id).removeprefix("ycloud-"))
                new_patient_payload = _new_patient_proposal_payload(
                    full_name.strip(), validated_dni.value, contact_phone
                )
                pending_action = await propose_appointment.execute(
                    conversation_id, CREATE_PATIENT_ACTION, new_patient_payload
                )
                await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
                return {
                    "response_text": _new_patient_confirmation_message(
                        full_name.strip(), validated_dni.value
                    ),
                    "response_buttons": _CONFIRM_BUTTONS,
                    "requires_handoff": False,
                    "pending_action_id": pending_action.id,
                    "collected_data": {**collected_data, "stage": STAGE_AWAITING_CONFIRMATION},
                }
            patient_primitives = _patient_to_primitives(identified_patient)
            if collected_data.get("operation") == CREATE_APPOINTMENT_ACTION:
                return await _propose_selected_slot(
                    conversation_id, patient_primitives, collected_data
                )
            return await _offer_appointments(
                conversation_id, patient_primitives, identified_patient.id, collected_data
            )

        if stage == STAGE_AWAITING_SPECIALTY_SELECTION:
            options = cast(list[Specialty], collected_data.get("specialty_options", []))
            if not options:
                return await _offer_specialties(conversation_id, collected_data)

            # Navigation rows for the paginated specialty list: 'Ver más'
            # re-renders the next page, 'Volver atrás' pops back to the
            # main menu (this list is the flow's entry screen).
            if state["button_payload"] == LIST_MORE_PAYLOAD:
                next_page = cast(int, collected_data.get("specialties_page", 0) or 0) + 1
                return await _offer_specialties(
                    conversation_id, {**collected_data, "specialties_page": next_page}
                )
            if state["button_payload"] == LIST_BACK_PAYLOAD:
                await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": WELCOME_TEXT,
                    "response_buttons": None,
                    "response_list": WELCOME_LIST,
                    "requires_handoff": False,
                    "pending_action_id": None,
                    "collected_data": {},
                }

            # These stages now send list rows, so a `SPECIALTY:{id}` tap
            # resolves deterministically; anything else (stale payload,
            # free text) still falls back to number/name matching.
            button_payload = state["button_payload"]
            button_index = (
                next(
                    (
                        index
                        for index, option in enumerate(options)
                        if button_payload == f"{SPECIALTY_PAYLOAD_PREFIX}{option.id}"
                    ),
                    None,
                )
                if button_payload is not None
                else None
            )
            index = (
                button_index
                if button_index is not None
                else (
                    None
                    if state["button_payload"] is not None
                    else _resolve_choice(state["user_message"], [option.name for option in options])
                )
            )
            if index is None:
                retry_count = cast(int, collected_data.get("specialty_retry_count", 0)) + 1
                listing = _numbered_list([option.name for option in options])
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "specialty_retry",
                    {
                        "situacion": (
                            "El paciente no eligió una especialidad válida de la lista "
                            "numerada que le mostramos."
                        ),
                        "instruccion": (
                            "Pedile que responda con el número de la especialidad. NO "
                            "repitas la lista, se la agregamos nosotros abajo."
                        ),
                        "intentos_seguidos": retry_count,
                    },
                    _SPECIALTY_NOT_UNDERSTOOD_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": f"{text}\n\n{listing}",
                    "response_buttons": [_MAIN_MENU_BUTTON],
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "specialty_retry_count": retry_count,
                    },
                }

            chosen = options[index]
            return await _offer_professionals(
                conversation_id, chosen.id, chosen.name, collected_data
            )

        if stage == STAGE_AWAITING_PROFESSIONAL_SELECTION:
            professional_options = cast(
                list[Professional], collected_data.get("professional_options", [])
            )
            specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
            if not professional_options or specialty_id is None:
                return await _offer_specialties(conversation_id, collected_data)

            # Navigation rows for the paginated professionals list:
            # 'Ver más' advances the page, 'Volver atrás' pops back to the
            # specialty list (the immediately previous screen).
            if state["button_payload"] == LIST_MORE_PAYLOAD:
                next_page = cast(int, collected_data.get("doctors_page", 0) or 0) + 1
                return await _offer_professionals(
                    conversation_id,
                    specialty_id,
                    str(collected_data.get("chosen_specialty_name", "")),
                    {**collected_data, "doctors_page": next_page},
                )
            if state["button_payload"] == LIST_BACK_PAYLOAD:
                return await _offer_specialties(conversation_id, collected_data)

            # A `PROFESSIONAL:{id}` row tap resolves deterministically;
            # anything else (stale payload, free text) still falls back to
            # number/name matching.
            button_payload = state["button_payload"]
            button_index = (
                next(
                    (
                        index
                        for index, option in enumerate(professional_options)
                        if button_payload == f"{PROFESSIONAL_PAYLOAD_PREFIX}{option.id}"
                    ),
                    None,
                )
                if button_payload is not None
                else None
            )
            index = (
                button_index
                if button_index is not None
                else (
                    None
                    if state["button_payload"] is not None
                    else _resolve_choice(
                        state["user_message"], [option.full_name for option in professional_options]
                    )
                )
            )
            if index is None:
                retry_count = cast(int, collected_data.get("professional_retry_count", 0)) + 1
                listing = _numbered_list([option.full_name for option in professional_options])
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "professional_retry",
                    {
                        "situacion": (
                            "El paciente no eligió un profesional válido de la lista "
                            "numerada que le mostramos."
                        ),
                        "instruccion": (
                            "Pedile que responda con el número del profesional. NO "
                            "repitas la lista, se la agregamos nosotros abajo."
                        ),
                        "intentos_seguidos": retry_count,
                    },
                    _PROFESSIONAL_NOT_UNDERSTOOD_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": f"{text}\n\n{listing}",
                    "response_buttons": [_MAIN_MENU_BUTTON],
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "professional_retry_count": retry_count,
                    },
                }

            chosen_professional = professional_options[index]
            return await _offer_slots(
                conversation_id,
                None,
                {
                    **collected_data,
                    "chosen_professional_id": chosen_professional.id,
                    "chosen_professional_name": chosen_professional.full_name,
                },
            )

        if stage == STAGE_AWAITING_OPERATION_SELECTION:
            button_payload = state["button_payload"]
            operation = (
                _OPERATION_BY_PAYLOAD.get(button_payload) if button_payload is not None else None
            )
            if operation is None:
                return {
                    "response_text": _OPERATION_SELECTION_REMINDER,
                    "response_buttons": _OPERATION_BUTTONS,
                    "requires_handoff": False,
                }
            if operation == CREATE_APPOINTMENT_ACTION:
                # Booking a new appointment now starts from the specialty
                # (this session's brief). Reschedule/cancel keep asking
                # for identification first: both begin by listing THIS
                # patient's own appointments, and Dentalink has no way to
                # do that without knowing who the patient is.
                return await _offer_specialties(
                    conversation_id, {**collected_data, "operation": operation}
                )
            return await _begin_identification(
                conversation_id,
                {**collected_data, "operation": operation},
                state["recent_messages"],
                state["contact_memory_summary"],
            )

        # No stage yet. A button tap wins outright (PRD.md §6: deterministic
        # over guessed) — the welcome list's booking rows carry these exact
        # payloads directly, skipping the operation menu entirely. Absent
        # that, honour whatever the patient already said in prose —
        # `resolve_interaction` left the raw mentions here, and re-asking
        # for something they just told us is exactly what made this bot
        # feel like a form.
        button_payload = state["button_payload"]
        operation = (
            _OPERATION_BY_PAYLOAD.get(button_payload)
            if button_payload is not None
            else _OPERATION_BY_MENTION.get(str(collected_data.get("operation_mention") or ""))
        )
        specialty_mention = collected_data.get("specialty_mention")

        if specialty_mention is not None:
            specialties = await list_specialties.execute()
            index = _resolve_by_name(str(specialty_mention), [s.name for s in specialties])
            if index is not None:
                # A named specialty only ever means booking — you don't
                # cancel "an ortodoncia".
                chosen = specialties[index]
                return await _offer_professionals(
                    conversation_id,
                    chosen.id,
                    chosen.name,
                    {**collected_data, "operation": CREATE_APPOINTMENT_ACTION},
                )

        professional_mention = collected_data.get("professional_mention")
        if professional_mention is not None:
            # A patient who names a professional directly ("quiero un
            # turno con el doctor Carlos Adahenao") knows exactly who they
            # want — the specialty is what they don't need to say, and
            # nothing here used to read this mention at all (seen live:
            # the bot kept asking "Para qué especialidad?" and just
            # discarded the name it was already given).
            matched_professional = await match_named_professional(
                appointment_gateway, str(professional_mention)
            )
            if matched_professional is not None:
                specialties = await list_specialties.execute()
                specialty_name = next(
                    (s.name for s in specialties if s.id == matched_professional.specialty_id),
                    "esa especialidad",
                )
                await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": _CHOOSE_PROFESSIONAL_PROMPT,
                    "response_buttons": None,
                    "response_list": professionals_list_message(
                        [matched_professional], include_back=True
                    ),
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                        "operation": CREATE_APPOINTMENT_ACTION,
                        "chosen_specialty_id": matched_professional.specialty_id,
                        "chosen_specialty_name": specialty_name,
                        "professional_options": [matched_professional],
                        "doctors_page": 0,
                    },
                }

        if operation == CREATE_APPOINTMENT_ACTION:
            return await _offer_specialties(
                conversation_id, {**collected_data, "operation": operation}
            )
        if operation is not None:
            return await _begin_identification(
                conversation_id,
                {**collected_data, "operation": operation},
                state["recent_messages"],
                state["contact_memory_summary"],
            )

        situacion = (
            'El paciente tocó "Volver al Menú" para abandonar lo que estaba haciendo y '
            "empezar de nuevo."
            if returned_to_main_menu
            else (
                "El paciente quiere hacer algo con un turno, pero todavía no dijo "
                "si es para sacar uno nuevo, reagendar o cancelar."
            )
        )
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "operation_menu",
            {
                "situacion": situacion,
                "tono": "Cordial y breve, como alguien de la clínica atendiendo por WhatsApp.",
            },
            _MAIN_MENU_RESET_MESSAGE if returned_to_main_menu else _OPERATION_MENU_MESSAGE,
            state["recent_messages"],
            state["contact_memory_summary"],
        )
        return {
<<<<<<< Updated upstream
            "response_text": text,
=======
            "response_text": _operation_menu_message(state.get("known_patient_name")),
>>>>>>> Stashed changes
            "response_buttons": _OPERATION_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "stage": STAGE_AWAITING_OPERATION_SELECTION},
        }

    return node
