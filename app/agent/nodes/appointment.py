import asyncio
import logging
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from redis.asyncio import Redis

from app.agent.appointment_decision_subgraph import (
    AppointmentDecisionState,
    build_appointment_decision_graph,
)

#: Re-exported for backward compatibility: `specialties.py`/tests import
#: `SELECT_SLOT_PAYLOAD_PREFIX` from this module. The `as`-self-alias is
#: the standard idiom for telling ruff/pyflakes this is an intentional
#: re-export, not dead code.
from app.agent.nodes.appointment_selection import (
    SELECT_SLOT_PAYLOAD_PREFIX as SELECT_SLOT_PAYLOAD_PREFIX,
)
from app.agent.nodes.appointment_selection import (
    current_page,
    next_page,
    slot_by_id,
    slot_payload_id,
    text_leaks_a_name,
)
from app.agent.nodes.appointment_selection import (
    format_confirmation_datetime as _format_confirmation_datetime,
)
from app.agent.nodes.appointment_selection import (
    numbered_list as _numbered_list,
)
from app.agent.nodes.appointment_selection import (
    resolve_by_name as _resolve_by_name,
)
from app.agent.nodes.appointment_selection import (
    slots_list_message as _slots_list_message,
)
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.agent.workflow_state import invalidate_from
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
    MENU_APPOINTMENT_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    OPERATION_CANCEL_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    OPERATION_RESCHEDULE_PAYLOAD,
    OPERATION_VIEW_PAYLOAD,
)
from app.domain.value_objects.paginated_list import (
    professionals_list_message,
    specialties_list_message,
)
from app.domain.value_objects.phone_number import PhoneNumber
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.llm.exceptions import LLMProviderError
from app.infrastructure.ycloud.flows import (
    REGISTRATION_FLOW_SCREEN_ID,
    VERIFICATION_FLOW_SCREEN_ID,
)

logger = logging.getLogger(__name__)


#: Each day in the window is one sequential Dentalink request (the API only
#: filters `fecha` by exact day, never by range — see the gateway's own
#: docstring). A 30-day window meant walking up to 30 requests before ever
#: reaching "no hay turnos", which was enough on its own to trip Dentalink's
#: undocumented rate limit. 14 trades a little reach for far fewer requests.
_SEARCH_WINDOW = timedelta(days=14)
#: Dentalink's `/v5/agendas` has no range filter — the gateway walks ONE
#: sequential HTTP request per day in the window above, stopping early once
#: it has collected this many slots. Confirmed live: with no cap at all, a
#: professional with heavy availability makes the search walk all 14 days
#: before replying — one real search measured 8.3s. This still supports
#: three full "Ver más" pages (`PAGE_SIZE` rows each) before falling back
#: to whatever the window actually has.
_MAX_SLOTS_SEARCHED = 27

#: Maximum time to wait for staffed-specialty filtering before degrading
#: gracefully to showing all specialties. This prevents the first appointment
#: response from disappearing indefinitely when Dentalink is slow.
_STAFFED_SPECIALTY_TIMEOUT = timedelta(seconds=8)


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
#: Mirrors `app.agent.appointment_decision_subgraph.STAGE_AWAITING_
#: SPECIALTY_BROWSE_CHOICE` — same one-way-dependency duplication this
#: module already keeps for the specialty/professional/slot stages above
#: and below. Subgraph-owned only, never set by legacy code (create-flow
#: only — reschedule never reaches specialty selection at all).
STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE = "awaiting_specialty_browse_choice"
STAGE_AWAITING_PROFESSIONAL_SELECTION = "awaiting_professional_selection"
STAGE_AWAITING_IDENTIFICATION = "awaiting_identification"
#: Reached from `STAGE_AWAITING_IDENTIFICATION` only when `identify_patient`
#: finds no match — a patient not yet in Dentalink must give obra social and
#: mail too (this session's own brief) before creating their ficha, on top
#: of the full name + DNI already collected during identification. Free-
#: text only: `verification_flow_id`/`registration_flow_id`'s WhatsApp Flow
#: already asks for these same fields on its own form (see
#: `STAGE_AWAITING_REGISTRATION_FLOW`), so this stage is this flow's exact
#: free-text equivalent.
STAGE_AWAITING_NEW_PATIENT_DETAILS = "awaiting_new_patient_details"
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

#: Stages where changing an earlier, non-sensitive selection is safe. Confirmation
#: stages are intentionally excluded: a durable PendingAction must be rejected or
#: confirmed by its explicit buttons, never bypassed by free text.
_NAVIGABLE_STAGES = frozenset(
    {
        STAGE_AWAITING_SPECIALTY_SELECTION,
        STAGE_AWAITING_PROFESSIONAL_SELECTION,
        STAGE_AWAITING_SLOT_SELECTION,
        STAGE_AWAITING_IDENTIFICATION,
        STAGE_AWAITING_NEW_PATIENT_DETAILS,
        STAGE_AWAITING_NO_SLOTS_CHOICE,
        STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
        STAGE_AWAITING_RESCHEDULE_PROFESSIONAL_CHOICE,
    }
)

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
#: operation menu they already answered in words. "view" mirrors
#: `_OPERATION_BY_PAYLOAD`'s own `OPERATION_VIEW_PAYLOAD` entry below —
#: seen live: "Qué turnos tengo?" had no matching key here at all, so it
#: fell through past the CREATE-specific branch straight into offering
#: specialties (CREATE's own fresh-entry path) instead of asking for
#: name+DNI to look the patient's existing appointments up.
_OPERATION_BY_MENTION = {
    "create": CREATE_APPOINTMENT_ACTION,
    "reschedule": RESCHEDULE_APPOINTMENT_ACTION,
    "cancel": CANCEL_APPOINTMENT_ACTION,
    "view": RESCHEDULE_APPOINTMENT_ACTION,
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
#: `SELECT_SLOT_PAYLOAD_PREFIX` now lives in `appointment_selection.py`
#: (imported above) alongside the payload-resolution helpers that use it.
CONFIRM_APPOINTMENT_PAYLOAD = "CONFIRM_APPOINTMENT"
REJECT_APPOINTMENT_PAYLOAD = "REJECT_APPOINTMENT"
RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD = "RESCHEDULE_KEEP_PROFESSIONAL"
RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD = "RESCHEDULE_CHANGE_PROFESSIONAL"

#: Seen live: "No gracias" typed as free text at `STAGE_AWAITING_CONFIRMATION`
#: fell into the generic "solo podés confirmar o cancelar tocando un botón"
#: reminder — the LLM-generated reply ended up acknowledging the decline
#: ("dale, no hay problema...") while the code still reattached
#: `_CONFIRM_BUTTONS` to it, since nothing had actually rejected the
#: pending proposal. An unambiguous decline in free text is treated
#: exactly like tapping "Cancelar" instead — Confirmar/Cancelar must only
#: ever appear on an outstanding proposal (user's own explicit rule).
_DECLINE_KEYWORDS = (
    "no gracias",
    "no, gracias",
    "mejor no",
    "no quiero",
    "no lo quiero",
    "cancelalo",
    "cancélalo",
    "cancela eso",
    "cancelá eso",
    "olvidalo",
    "olvídalo",
    "dejalo",
    "déjalo",
    "no importa",
    "ya no",
    "no me sirve",
)


def _is_free_text_decline(text: str) -> bool:
    lowered = text.strip().casefold()
    if lowered in {"no", "nop", "no.", "nel"}:
        return True
    return any(keyword in lowered for keyword in _DECLINE_KEYWORDS)

#: No upper bound on digit count here — `Dni` (7-8 digits) is the real
#: gatekeeper for validity. Capping this at 9 used to truncate a longer
#: run (e.g. a 10-digit typo) and leak the leftover digit into the parsed
#: name instead of the whole thing failing `Dni`'s length check cleanly.
_DNI_PATTERN = re.compile(r"(\d{6,})")
#: Deliberately permissive (no full RFC 5322 validation) — same "good
#: enough to disambiguate free text, not a strict format gate" posture
#: `_DNI_PATTERN` already takes for DNI.
_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

_CHOOSE_SPECIALTY_PROMPT = "Para qué especialidad querés el turno? Elegí una opción de la lista:"
_NO_SPECIALTIES_MESSAGE = (
    "En este momento no tengo las especialidades disponibles. "
    "Querés que te comunique con administración?"
)
_CHOOSE_PROFESSIONAL_PROMPT = (
    "Con qué profesional preferís atenderte? Elegí una opción de la lista:"
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
_ASK_NEW_PATIENT_DETAILS_MESSAGE = (
    "No encontramos tu ficha en el sistema. Para crearla necesito también tu *obra "
    "social* y tu *mail* (por ejemplo: OSDE, rosa@gmail.com)."
)
_NEW_PATIENT_DETAILS_NOT_UNDERSTOOD_MESSAGE = (
    "No pude leer bien esos datos. Escribime tu obra social y tu mail juntos, "
    "por ejemplo: OSDE, rosa@gmail.com."
)
_ASK_NEW_PATIENT_EMAIL_ONLY_MESSAGE = (
    "Gracias! Ahora decime tu *mail*, por ejemplo: rosa@gmail.com."
)
_ASK_NEW_PATIENT_OBRA_SOCIAL_ONLY_MESSAGE = (
    "Gracias! Ahora decime tu *obra social*, por ejemplo: OSDE."
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
#: `STAGE_AWAITING_NO_AVAILABILITY_CHOICE` used to have no dedicated
#: handler at all — ANY button tap that wasn't literally `MENU_MAIN_
#: PAYLOAD` (already intercepted earlier in `node()`) fell through the
#: entire dispatch chain to the bottom "no stage yet" fallback,
#: indistinguishable from a fresh conversation. Live bug: a stale tap on
#: an old, already-superseded professional/specialty list (WhatsApp never
#: disables a past interactive message — there is no API for that) landed
#: here and silently reset into the generic operation menu instead of
#: telling the patient their tap was out of date.
_STALE_TAP_MESSAGE = "Esa opción ya no está disponible. Tocá el botón de abajo para seguir."
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
_CHOOSE_APPOINTMENT_TO_CANCEL_PROMPT = (
    "Elegí cuál turno querés cancelar tocando uno de los botones:"
)
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
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="🔄 Empezar de nuevo"),
]
_VIEW_OTHER_PROFESSIONALS_PAYLOAD = "VIEW_OTHER_PROFESSIONALS"
_NO_SLOTS_CHOICE_BUTTONS = [
    InteractiveButton(id=_VIEW_OTHER_PROFESSIONALS_PAYLOAD, title="Otros profesionales"),
]
_NO_AVAILABILITY_BUTTONS = [
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]
_RESCHEDULE_PROFESSIONAL_CHOICE_BUTTONS = [
    InteractiveButton(id=RESCHEDULE_KEEP_PROFESSIONAL_PAYLOAD, title="✅ Mismo profesional"),
    InteractiveButton(id=RESCHEDULE_CHANGE_PROFESSIONAL_PAYLOAD, title="🔄 Elegir otro"),
]
_RESCHEDULE_PROFESSIONAL_CHOICE_REMINDER = (
    "Por favor, elegí una opción tocando un botón: mantener el mismo profesional o elegir otro."
)


#: The field name asked of `LLMProvider.extract_information` to judge
#: whether a piece of text plausibly reads as a patient's full name.
_FULL_NAME_FIELD = "nombre_completo"


async def _extract_full_name(llm_provider: LLMProvider, text: str) -> str | None:
    """Uses the LLM to judge whether `text` plausibly reads as a person's
    full name rather than ordinary chatter, instead of a fixed keyword
    blocklist.

    A hardcoded word list (the old `_NON_NAME_WORDS`/`_looks_like_a_name`
    approach) can never cover every casual phrase a patient might send
    mid-identification — seen live: "Bien vos?" (replying to the bot's own
    "Cómo estás?") got registered as the patient's name, because neither
    "bien" nor "vos" happened to be on the list. Whack-a-mole word lists
    don't scale; judging plausibility is exactly what an LLM is for
    (this session's own brief).

    Fails safe on any LLM failure: treats unclear text as NOT a name
    (prompting a retry) rather than risking that same false-positive
    silently again.
    """
    try:
        result = await llm_provider.extract_information(text, [_FULL_NAME_FIELD])
    except LLMProviderError:
        return None
    if _FULL_NAME_FIELD in result.missing_fields:
        return None
    value = result.fields.get(_FULL_NAME_FIELD)
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _extract_identification_pieces(
    llm_provider: LLMProvider, text: str
) -> tuple[str | None, str | None]:
    """Splits free text into whichever (full_name, dni) pieces it actually
    contains — either can be missing, since the patient may answer across
    two messages instead of PRD.md §32's suggested one-shot format
    ("Rosa Gómez, 30123456"). A 6+ digit run anywhere is the DNI; whatever
    surrounds it is checked against `_extract_full_name` before being
    accepted as the name (rather than accepted unconditionally) — with no
    digit run at all, the whole message is checked the same way.
    """
    match = _DNI_PATTERN.search(text)
    if match is not None:
        dni = match.group(1)
        remainder = re.sub(r"\s+", " ", text[: match.start()] + text[match.end() :]).strip(" ,.-")
        full_name = await _extract_full_name(llm_provider, remainder) if remainder else None
        return full_name, dni
    stripped = text.strip()
    if not stripped:
        return None, None
    return await _extract_full_name(llm_provider, stripped), None


def _extract_new_patient_details(
    text: str,
    remembered_obra_social: str | None,
    remembered_email: str | None,
) -> tuple[str | None, str | None]:
    """Splits free text into whichever (obra_social, email) pieces it
    actually contains — mirrors `_extract_identification_pieces`'s own
    "either can be missing, answer may span two messages" contract, using
    `_EMAIL_PATTERN` the same way that function uses `_DNI_PATTERN`: an
    email is distinctive enough to find directly, and whatever remains is
    the obra social name. Unlike the name/DNI pair, obra social has no
    fixed shape to validate — accepted as free text, same as the
    registration Flow's own `obra_social` field does (only ever matched
    best-effort against `AgreementGateway.find_agreement_by_name`, never
    rejected if unmatched).

    A piece the patient addresses this turn always overrides what was
    remembered, same convention as `_merge_identification`.
    """
    match = _EMAIL_PATTERN.search(text)
    if match is not None:
        email = match.group(0)
        remainder = re.sub(r"\s+", " ", text[: match.start()] + text[match.end() :]).strip(" ,.-")
        obra_social = remainder if remainder else remembered_obra_social
        return obra_social, email
    stripped = text.strip()
    if not stripped:
        return remembered_obra_social, remembered_email
    return stripped, remembered_email


#: Numbered-choice/name resolution, list-choice resolution (row tap vs.
#: free-text number/name fallback), and `_numbered_list` rendering all now
#: live in `appointment_selection.py` (imported above as `_resolve_by_name`,
#: `resolve_list_choice`, and `_numbered_list`) — extracted with no
#: behavior change so the create-selection subgraph (PR 2) can reuse them.


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



async def _staffed_specialty_ids_safe(gateway: AppointmentGateway) -> set[str] | None:
    """Wrapper that applies a timeout to the staffed-specialty lookup.

    If the lookup exceeds the timeout or raises an exception, we return
    ``None`` instead of a set. The caller interprets ``None`` as "show all
    specialties" rather than filtering, so the patient still gets a
    response instead of a frozen UI.
    """
    try:
        return await asyncio.wait_for(
            staffed_specialty_ids(gateway), timeout=_STAFFED_SPECIALTY_TIMEOUT.total_seconds()
        )
    except Exception as exc:  # noqa: BLE001 -- broad catch is intentional
        logger.warning(
            "staffed_specialty_ids lookup failed or timed out; showing all specialties",
            exc_info=exc,
        )
        return None

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


async def _merge_identification(
    llm_provider: LLMProvider,
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

    Only ever called from `STAGE_AWAITING_IDENTIFICATION` (see this node's
    `node()` dispatch). A message with no digit run is checked against
    `_extract_full_name` (LLM-judged, not a keyword blocklist) rather than
    assumed to always be a bare name — bug found live: a name-first answer
    with no chitchat guard at all discarded a real name whenever no DNI
    was on record yet (e.g. "Pedro Cassera" then "30131313" — by the time
    the DNI arrived, the name had never been remembered and got asked for
    AGAIN even though the patient already typed it); a fixed keyword
    blocklist instead let unrelated chatter ("Bien vos?") through as if it
    were a name. The LLM check needs to accept a real name-first answer
    AND reject ordinary chatter — a blocklist can only ever do one of those
    reliably.
    """
    full_name, dni = await _extract_identification_pieces(llm_provider, text)
    return (
        full_name if full_name is not None else remembered_full_name,
        dni if dni is not None else remembered_dni,
    )


#: `_format_slot_option` and `_slots_list_message` now live in
#: `appointment_selection.py` (imported above) — same no-behavior-change
#: extraction as the payload/pagination helpers.


def _appointment_button(appointment: Appointment) -> InteractiveButton:
    return InteractiveButton(
        id=f"{SELECT_APPOINTMENT_PAYLOAD_PREFIX}{appointment.id}",
        title=appointment.slot.time_range.start.strftime("%d/%m %H:%M"),
    )


#: Every LLM-framed message below that carries a real booking's date/time
#: follows the same shape: the model only ever writes the surrounding
#: framing (opening line, closing question), NEVER the date/time itself —
#: that block is always formatted by code (`_format_confirmation_datetime`)
#: and appended verbatim after the model's text. A patient showing up on
#: the wrong day because a paraphrase dropped or mangled a digit is a much
#: worse failure than a slightly repetitive sentence, so this data never
#: passes through free-form generation (user's own explicit call).
async def _confirmation_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    slot: AppointmentSlot,
    professional_names: dict[str, str],
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    datetime_block = _format_confirmation_datetime(slot.time_range.start)
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "propose_create_confirmation",
        {
            "situacion": (
                "Encontramos un horario disponible para el turno que el paciente quiere "
                "sacar y hay que preguntarle si confirma la reserva."
            ),
            "profesional": professional_name,
            "instruccion": (
                "Decí que hay un horario disponible con ese profesional y terminá "
                "preguntando si confirma la reserva. NO menciones fecha ni hora — esos "
                "datos se agregan aparte, después de tu mensaje, tal cual vienen."
            ),
        },
        f"Tengo disponible con {professional_name}.\n\nConfirmás que querés reservar este turno?",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{datetime_block}"


async def _cancel_confirmation_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    appointment: Appointment,
    professional_names: dict[str, str],
    patient_name: str | None,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    slot = appointment.slot
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    datetime_block = _format_confirmation_datetime(slot.time_range.start)
    context: dict[str, object] = {
        "situacion": (
            "El paciente pidió cancelar un turno y hay que pedirle que confirme antes de "
            "hacerlo, para que el horario quede liberado."
        ),
        "profesional": professional_name,
        "instruccion": (
            "Pedile que confirme que quiere cancelar ese turno con ese profesional, así el "
            "horario queda liberado. NO menciones fecha ni hora — esos datos se agregan "
            "aparte, después de tu mensaje, tal cual vienen."
        ),
    }
    if patient_name:
        context["nombre_paciente"] = patient_name
        context["instruccion"] = (
            f"{context['instruccion']} Podés dirigirte a {patient_name} por su nombre."
        )
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "propose_cancel_confirmation",
        context,
        f"Vas a cancelar tu turno con {professional_name}.\n\nConfirmás que querés cancelarlo?",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{datetime_block}"


async def _reschedule_confirmation_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    slot: AppointmentSlot,
    professional_names: dict[str, str],
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    professional_name = professional_names.get(slot.professional_id, "Profesional")
    datetime_block = _format_confirmation_datetime(slot.time_range.start)
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "propose_reschedule_confirmation",
        {
            "situacion": (
                "El paciente eligió un nuevo horario para reagendar su turno y hay que "
                "confirmarlo antes de hacer el cambio."
            ),
            "profesional": professional_name,
            "instruccion": (
                "Decí que va a reagendar el turno a ese horario con ese profesional y "
                "terminá preguntando si confirma el cambio. NO menciones fecha ni hora — "
                "esos datos se agregan aparte, después de tu mensaje, tal cual vienen."
            ),
        },
        f"Vas a reagendar tu turno con {professional_name}.\n\nConfirmás el cambio?",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{datetime_block}"


async def _new_patient_confirmation_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    full_name: str,
    dni: str,
    obra_social: str,
    email: str,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    data_block = f"Nombre: {full_name}\nDNI: {dni}\nObra social: {obra_social}\nMail: {email}"
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "propose_new_patient_confirmation",
        {
            "situacion": (
                "No encontramos al paciente registrado con esos datos — hay que "
                "confirmarle que quiere crear su ficha antes de hacerlo."
            ),
            "instruccion": (
                "Decí que no encontramos a nadie registrado con esos datos y preguntá si "
                "confirma crear su ficha. NO reescribas ninguno de sus datos — se agregan "
                "aparte, después de tu mensaje, tal cual vienen."
            ),
        },
        "No encontramos ningún paciente registrado con esos datos. "
        "Confirmás que querés crear tu ficha con estos datos?",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{data_block}"


def _new_patient_proposal_payload(
    full_name: str, dni: str, phone: PhoneNumber, obra_social: str, email: str
) -> dict[str, object]:
    return {
        "full_name": full_name,
        "dni": dni,
        "phone": str(phone),
        "obra_social": obra_social,
        "email": email,
    }


async def _verification_confirmation_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    patient: Patient,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    data_block = f"Nombre: {patient.full_name}\nDNI: {patient.dni}"
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "propose_verification_confirmation",
        {
            "situacion": (
                "Encontramos al paciente registrado y hay que confirmar que estos datos "
                "son correctos."
            ),
            "instruccion": (
                "Preguntá si estos datos son correctos. NO reescribas el nombre ni el "
                "DNI — esos datos se agregan aparte, después de tu mensaje, tal cual vienen."
            ),
        },
        "Encontramos estos datos, ¿son correctos?",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{data_block}"


async def _success_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    appointment: Appointment,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    slot = appointment.slot
    datetime_block = _format_confirmation_datetime(slot.time_range.start)
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "create_success",
        {
            "situacion": "El turno se creó con éxito en Dentalink — hay que avisarle al paciente.",
            "instruccion": (
                "Decí con calidez que el turno quedó confirmado y que lo esperan en la "
                "clínica. NO menciones fecha ni hora — esos datos se agregan aparte, "
                "después de tu mensaje, tal cual vienen."
            ),
        },
        "✅ Tu turno quedó confirmado.\n\nTe esperamos en la clínica.",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{datetime_block}"


async def _reschedule_success_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    appointment: Appointment,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    slot = appointment.slot
    datetime_block = _format_confirmation_datetime(slot.time_range.start)
    text = await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "reschedule_success",
        {
            "situacion": (
                "El turno se reagendó con éxito en Dentalink — hay que avisarle al paciente."
            ),
            "instruccion": (
                "Decí con calidez que reagendaron el turno y que lo esperan en la clínica. "
                "NO menciones fecha ni hora — esos datos se agregan aparte, después de tu "
                "mensaje, tal cual vienen."
            ),
        },
        "✅ Reagendamos tu turno.\n\nTe esperamos en la clínica.",
        recent_messages,
        contact_memory,
    )
    return f"{text}\n\n{datetime_block}"


async def _cancel_success_message(
    llm_provider: LLMProvider,
    conversation_id: ConversationId,
    patient_name: str | None,
    recent_messages: list[dict[str, str]],
    contact_memory: str | None,
) -> str:
    context: dict[str, object] = {
        "situacion": "El turno se canceló con éxito en Dentalink — hay que avisarle al paciente.",
        "instruccion": (
            "Agradecele por avisar y comentale que, si tiene cualquier duda, puede hablar "
            "con administración."
        ),
    }
    fallback = "✅ Cancelamos tu turno. Si tenés cualquier duda, podés hablar con administración."
    if patient_name:
        context["nombre_paciente"] = patient_name
        context["instruccion"] = f"{context['instruccion']} Podés agradecerle por su nombre."
        fallback = (
            f"✅ Cancelamos tu turno, {patient_name}. Si tenés cualquier duda, podés hablar "
            "con administración."
        )
    return await generate_or_fallback(
        llm_provider,
        str(conversation_id),
        "cancel_success",
        context,
        fallback,
        recent_messages,
        contact_memory,
    )


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


def should_use_appointment_decision_subgraph(
    stage: str | None, collected_data: dict[str, object]
) -> bool:
    """True when the migrated create-selection subgraph
    (`app.agent.appointment_decision_subgraph`) should own this turn
    instead of the legacy FSM branches in `node(...)` below.

    First slice only: `STAGE_AWAITING_SPECIALTY_SELECTION`,
    `STAGE_AWAITING_PROFESSIONAL_SELECTION`, and
    `STAGE_AWAITING_SLOT_SELECTION` delegate unconditionally (they're
    create-booking-only stages in this codebase already), except a
    still-in-flight reschedule (`rescheduling_appointment_id` present)
    always stays legacy-owned — RESCHEDULE identifies the patient up
    front and proposes immediately, which this first slice never does.
    With no stage yet, only an already-resolved create-booking operation
    delegates; every other operation (reschedule/cancel/view) and the
    specialty/professional free-text-mention shortcuts stay legacy-owned.

    Rollback point (PR 2's own): disable/remove this predicate's call
    sites in `node(...)` to fall back to the legacy FSM entirely — PR 1's
    extracted helpers in `appointment_selection.py` stay in place either way.
    """
    if collected_data.get("rescheduling_appointment_id") is not None:
        return False
    if stage in (
        STAGE_AWAITING_SPECIALTY_SELECTION,
        STAGE_AWAITING_PROFESSIONAL_SELECTION,
        STAGE_AWAITING_SLOT_SELECTION,
    ):
        return True
    if stage is None:
        return collected_data.get("operation") == CREATE_APPOINTMENT_ACTION
    return False


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
    appointment_decision_graph = build_appointment_decision_graph(
        appointment_gateway=appointment_gateway,
        specialty_gateway=specialty_gateway,
        conversation_repository=conversation_repository,
        llm_provider=llm_provider,
    )

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

    async def _ask_new_patient_details_message(
        conversation_id: ConversationId,
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> str:
        """Free-text equivalent of the registration Flow's own form — asks
        for obra social and mail once `identify_patient` found no match
        (this session's own brief: creating a ficha needs both, on top of
        the full name + DNI already collected during identification)."""
        return await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "ask_new_patient_details",
            {
                "situacion": (
                    "No encontramos al paciente registrado — para crear su ficha todavía "
                    "hacen falta su obra social y su mail."
                ),
                "formato_requerido": (
                    "Obra social y mail, en un mismo mensaje o en dos, ejemplo: OSDE, "
                    "rosa@gmail.com. Incluí ese ejemplo en tu respuesta."
                ),
            },
            _ASK_NEW_PATIENT_DETAILS_MESSAGE,
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

    async def _delegate_to_decision_subgraph(
        state: AgentState, collected_data: dict[str, object]
    ) -> dict[str, object]:
        """Projects `AgentState` into `AppointmentDecisionState`, invokes the
        compiled create-selection subgraph, and converts its result back
        into partial `AgentState` updates.

        `collected_data` is the caller's already-decided projection (the
        node-level `collected_data`, or that plus a freshly resolved
        `operation` for the "no stage yet" fallback) — never re-derived
        here, so the caller stays in control of exactly what data crosses
        the boundary (design's "narrow state projection" requirement).
        """
        conversation_id = ConversationId(state["conversation_id"])
        decision_state: AppointmentDecisionState = {
            "conversation_id": state["conversation_id"],
            "user_message": state["user_message"],
            "button_payload": state["button_payload"],
            "recent_messages": state["recent_messages"],
            "contact_memory_summary": state["contact_memory_summary"],
            "pending_action_id": state.get("pending_action_id"),
            "collected_data": collected_data,
        }
        result = await appointment_decision_graph.ainvoke(decision_state)

        if result.get("exit_reason") == "begin_identification":
            return await _begin_identification(
                conversation_id,
                cast(dict[str, object], result["collected_data"]),
                state["recent_messages"],
                state["contact_memory_summary"],
            )

        # A migrated node that didn't touch `collected_data`/`pending_action_id`
        # this turn (a reminder/stale-payload response) must not report them
        # as changed either — same "collected_data"/"pending_action_id" key
        # omission the legacy FSM branches rely on (LangGraph merges a
        # partial update onto the prior turn's value either way).
        updates: dict[str, object] = {
            "response_text": result.get("response_text"),
            "response_buttons": result.get("response_buttons"),
            "requires_handoff": result.get("requires_handoff", False),
        }
        if result.get("response_list") is not None:
            updates["response_list"] = result["response_list"]
        if result.get("response_flow") is not None:
            updates["response_flow"] = result["response_flow"]
        if result.get("collected_data") != collected_data:
            updates["collected_data"] = result.get("collected_data")
        if result.get("pending_action_id") != state.get("pending_action_id"):
            updates["pending_action_id"] = result.get("pending_action_id")
        return updates

    async def _cancel_follow_up(repositories: ProposalRepositories, pending_action_id: str) -> None:
        scheduled_actions = repositories.scheduled_actions
        scheduled_action = await scheduled_actions.get_by_pending_action_id(pending_action_id)
        if scheduled_action is not None:
            await scheduled_actions.transition_status(
                scheduled_action.id, from_status="scheduled", to_status="cancelled"
            )

    async def _offer_specialties(
        conversation_id: ConversationId,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        specialties = await list_specialties.execute()
        staffed = await _staffed_specialty_ids_safe(appointment_gateway)
        if staffed is not None:
            specialties = [s for s in specialties if s.id in staffed]
        if not specialties:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_specialties",
                {"situacion": "No hay especialidades cargadas en este momento."},
                _NO_SPECIALTIES_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": text,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": {},
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = current_page(collected_data, "specialties_page")
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "choose_specialty",
            {
                "situacion": (
                    "Hay que preguntarle para qué especialidad quiere el turno; le vamos a "
                    "mostrar una lista de especialidades para elegir."
                ),
                # Seen live: without this, the model would list the actual
                # specialty names in its own free-text reply, which is
                # redundant with the interactive list rendered right below
                # it — the same suppression `_offer_appointments` already
                # applies to its own list.
                "instruccion": (
                    "Le vamos a mostrar la lista de especialidades debajo de tu mensaje — NO "
                    "las menciones ni las repitas, solo invitá a elegir una."
                ),
            },
            _CHOOSE_SPECIALTY_PROMPT,
            recent_messages,
            contact_memory,
        )
        if text_leaks_a_name(text, [s.name for s in specialties]):
            text = _CHOOSE_SPECIALTY_PROMPT
        return {
            "response_text": text,
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
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
        exclude_professional_id: str | None = None,
    ) -> dict[str, object]:
        professionals = await appointment_gateway.list_professionals(specialty_id=specialty_id)
        if exclude_professional_id is not None:
            # Seen live: "ver otros profesionales" (reached after a
            # professional was just confirmed to have zero availability)
            # kept re-listing that exact same professional — the patient
            # picked them again, got told the same "no hay lugares" a
            # second time, for no reason. Only ever passed from
            # STAGE_AWAITING_NO_SLOTS_CHOICE's own handler, never from
            # this function's other call sites (a fresh specialty pick has
            # nothing to exclude).
            professionals = [p for p in professionals if p.id != exclude_professional_id]
        if not professionals:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_professionals",
                {
                    "situacion": (
                        f"No hay profesionales cargados para la especialidad {specialty_name}."
                    ),
                },
                _NO_PROFESSIONALS_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": text,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": {},
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = current_page(collected_data, "doctors_page")
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "choose_professional",
            {
                "situacion": (
                    "Hay que preguntarle con qué profesional prefiere atenderse; le vamos a "
                    "mostrar una lista para elegir."
                ),
                "instruccion": (
                    "Le vamos a mostrar la lista de profesionales debajo de tu mensaje — NO "
                    "los menciones ni los repitas, solo invitá a elegir uno."
                ),
            },
            _CHOOSE_PROFESSIONAL_PROMPT,
            recent_messages,
            contact_memory,
        )
        if text_leaks_a_name(text, [p.full_name for p in professionals]):
            text = _CHOOSE_PROFESSIONAL_PROMPT
        return {
            "response_text": text,
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
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
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
            limit=_MAX_SLOTS_SEARCHED,
        )
        if not slots and collected_data.get("chosen_specialty_id") is not None:
            # A specialty is already known — offer another professional in
            # it before falling back to "start over from scratch" (this
            # session's own brief: a professional with zero availability
            # used to only offer "Menú principal", discarding the
            # specialty the patient already picked).
            await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_slots_other_professionals",
                {
                    "situacion": (
                        "No hay horarios disponibles con ese profesional en los próximos "
                        "días; ofrecele ver otros profesionales de la misma especialidad."
                    ),
                },
                _NO_SLOTS_OTHER_PROFESSIONALS_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": text,
                "response_buttons": _NO_SLOTS_CHOICE_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {
                    **collected_data,
                    "stage": STAGE_AWAITING_NO_SLOTS_CHOICE,
                },
            }
        if not slots:
            await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_slots",
                {
                    "situacion": (
                        "No hay horarios disponibles en los próximos días; ofrecele pasarlo "
                        "con administración."
                    ),
                },
                _NO_SLOTS_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": text,
                "response_buttons": _NO_AVAILABILITY_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {
                    **collected_data,
                    "stage": STAGE_AWAITING_NO_AVAILABILITY_CHOICE,
                },
            }

        professionals = await appointment_gateway.list_professionals()
        professional_names = {
            professional.id: professional.full_name for professional in professionals
        }
        page = current_page(collected_data, "slots_page")
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "choose_slot",
            {
                "situacion": "Hay horarios disponibles y hay que invitar al paciente a elegir uno.",
                "instruccion": (
                    "Le vamos a mostrar una lista de horarios debajo de tu mensaje — NO "
                    "los menciones ni los repitas, solo invitá a elegir uno."
                ),
            },
            _CHOOSE_SLOT_PROMPT,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": text,
            "response_buttons": None,
            "response_list": _slots_list_message(slots, page=page, include_back=True),
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_SLOT_SELECTION,
                # Never let an explicit `None` here (the CREATE flow's own
                # "not identified yet" state) erase a patient RESCHEDULE
                # already identified earlier in `collected_data`.
                "patient": patient if patient is not None else collected_data.get("patient"),
                "available_slots": slots,
                "professional_names": professional_names,
                "slots_page": page,
            },
        }

    async def _propose_selected_slot(
        conversation_id: ConversationId,
        patient: dict[str, object],
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        """Proposes the slot the patient already picked, now that we know
        who they are — never re-searches availability."""
        selected = cast(AppointmentSlot | None, collected_data.get("pending_selected_slot"))
        if selected is None:
            session_lost_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "session_lost",
                {"situacion": "Se perdió el contexto de la conversación."},
                _SESSION_LOST_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": session_lost_text,
                "response_buttons": None,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {},
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
        confirmation_text = await _confirmation_message(
            llm_provider,
            conversation_id,
            selected,
            professional_names,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": confirmation_text,
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
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        appointments = await get_patient_appointments.execute(patient_id)
        if not appointments:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_appointments",
                {"situacion": "No encontramos turnos próximos a nombre del paciente."},
                _NO_APPOINTMENTS_MESSAGE,
                recent_messages,
                contact_memory,
            )
            return {
                "response_text": text,
                "response_buttons": None,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {},
            }

        professionals = await appointment_gateway.list_professionals()
        professional_names = {
            professional.id: professional.full_name for professional in professionals
        }
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        # Operation-specific framing — CANCEL, RESCHEDULE and VIEW all reach
        # this same "pick which appointment" screen, but the tone must not
        # be interchangeable: seen live, a generic "invitá a elegir uno"
        # situacion left the model free to default to upbeat booking
        # phrasing ("te lo reservo y listo") even while the patient was
        # canceling. A single shared `intent="choose_appointment"` also let
        # the very next confirmation turn pick up that booking TONE via
        # `recent_messages`, even though that turn's own instruction
        # already forbids repeating the date/time itself.
        if collected_data.get("operation") == CANCEL_APPOINTMENT_ACTION:
            intent = "choose_appointment_to_cancel"
            situacion = "El paciente quiere cancelar un turno — hay que pedirle que elija cuál."
            fallback = _CHOOSE_APPOINTMENT_TO_CANCEL_PROMPT
        else:
            intent = "choose_appointment_to_reschedule"
            situacion = (
                "El paciente quiere ver o reprogramar un turno — hay que pedirle que elija cuál."
            )
            fallback = _CHOOSE_APPOINTMENT_PROMPT
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            intent,
            {
                "situacion": situacion,
                "instruccion": (
                    "Le vamos a mostrar una lista de sus turnos debajo de tu mensaje — NO "
                    "los menciones ni los repitas, solo invitá a elegir uno. No uses tono de "
                    "reserva ni digas que se lo vas a agendar."
                ),
            },
            fallback,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": text,
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

        # A navigation request comes from the global router. Move back only as
        # far as requested and invalidate dependent selections, never patient
        # identity or independent workflow data.
        navigation_target = collected_data.get("navigation_target")
        if stage in _NAVIGABLE_STAGES and isinstance(navigation_target, str):
            navigation_data = {
                key: value for key, value in collected_data.items() if key != "navigation_target"
            }
            if navigation_target == "main":
                await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": WELCOME_TEXT,
                    "response_buttons": None,
                    "response_list": WELCOME_LIST,
                    "requires_handoff": False,
                    "pending_action_id": None,
                    "collected_data": {},
                }
            if navigation_target in {"service", "specialty"}:
                return await _offer_specialties(
                    conversation_id,
                    invalidate_from(navigation_data, "specialty"),
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            if navigation_target == "professional":
                repaired = invalidate_from(navigation_data, "professional")
                specialty_id = cast(str | None, repaired.get("chosen_specialty_id"))
                if specialty_id is not None:
                    return await _offer_professionals(
                        conversation_id,
                        specialty_id,
                        str(repaired.get("chosen_specialty_name", "esa especialidad")),
                        repaired,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                return await _offer_specialties(
                    conversation_id,
                    repaired,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            if navigation_target == "slot":
                repaired = invalidate_from(navigation_data, "slot")
                if repaired.get("chosen_professional_id") is not None:
                    patient = cast(dict[str, object] | None, repaired.get("patient"))
                    return await _offer_slots(
                        conversation_id,
                        patient,
                        repaired,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                specialty_id = cast(str | None, repaired.get("chosen_specialty_id"))
                if specialty_id is not None:
                    return await _offer_professionals(
                        conversation_id,
                        specialty_id,
                        str(repaired.get("chosen_specialty_name", "esa especialidad")),
                        repaired,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                return await _offer_specialties(
                    conversation_id,
                    repaired,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )

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
            collected_data = {}
            stage = None
            returned_to_main_menu = True

        if stage == STAGE_AWAITING_CONFIRMATION:
            pending_action_id = state.get("pending_action_id")
            button_payload = state["button_payload"]
            if (
                button_payload is None
                and pending_action_id is not None
                and _is_free_text_decline(state["user_message"])
            ):
                # Normalize onto the exact same path a "Cancelar" tap
                # takes below — never a separate branch, so there is only
                # one place that decides what a decline looks like.
                button_payload = REJECT_APPOINTMENT_PAYLOAD

            if button_payload is None or pending_action_id is None:
                confirmation_reminder_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "confirmation_reminder",
                    {
                        "situacion": (
                            "El paciente escribió texto libre pero en este paso solo se "
                            "puede confirmar o cancelar tocando uno de los 2 botones."
                        ),
                    },
                    _CONFIRMATION_REMINDER,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": confirmation_reminder_text,
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
                proposal_rejected_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "proposal_rejected",
                    {"situacion": "El paciente decidió no confirmar la propuesta anterior."},
                    _PROPOSAL_REJECTED_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": proposal_rejected_text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "pending_action_id": None,
                    "collected_data": {**collected_data, "stage": None},
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
                    proposal_not_found_text = await generate_or_fallback(
                        llm_provider,
                        str(conversation_id),
                        "proposal_not_found",
                        {
                            "situacion": (
                                "No encontramos la propuesta de turno que el paciente confirmó."
                            ),
                        },
                        _PROPOSAL_NOT_FOUND_MESSAGE,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    return {
                        "response_text": proposal_not_found_text,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {**collected_data, "stage": None},
                    }
                if isinstance(confirm_error, PendingActionExpiredError):
                    patient = cast(dict[str, object] | None, collected_data.get("patient"))
                    if patient is None:
                        session_lost_text = await generate_or_fallback(
                            llm_provider,
                            str(conversation_id),
                            "session_lost",
                            {"situacion": "Se perdió el contexto de la conversación."},
                            _SESSION_LOST_MESSAGE,
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                        return {
                            "response_text": session_lost_text,
                            "response_buttons": None,
                            "requires_handoff": False,
                            "pending_action_id": None,
                            "collected_data": {},
                        }
                    offer = await _offer_slots(
                        conversation_id,
                        patient,
                        collected_data,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    expired_notice = await generate_or_fallback(
                        llm_provider,
                        str(conversation_id),
                        "proposal_expired",
                        {
                            "situacion": (
                                "La propuesta de turno anterior venció porque no llegó una "
                                "confirmación a tiempo; le vamos a mostrar horarios de nuevo."
                            ),
                        },
                        _PROPOSAL_NO_LONGER_VALID_MESSAGE,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    offer["response_text"] = f"{expired_notice}\n\n{offer['response_text']}"
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
                    cancel_success_patient = cast(
                        dict[str, object] | None, collected_data.get("patient")
                    )
                    cancel_success_text = await _cancel_success_message(
                        llm_provider,
                        conversation_id,
                        (
                            str(cancel_success_patient["full_name"])
                            if cancel_success_patient
                            else None
                        ),
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    return {
                        "response_text": cancel_success_text,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {"post_action_context": CANCEL_APPOINTMENT_ACTION},
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
                            conversation_id,
                            _patient_to_primitives(patient_entity),
                            collected_data,
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                        slot_taken_notice = await generate_or_fallback(
                            llm_provider,
                            str(conversation_id),
                            "slot_taken",
                            {
                                "situacion": (
                                    "El horario que el paciente había elegido se ocupó justo "
                                    "mientras confirmábamos, no se hizo ningún cambio; le "
                                    "vamos a mostrar horarios nuevos."
                                ),
                            },
                            _SLOT_TAKEN_MESSAGE,
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                        offer["response_text"] = f"{slot_taken_notice}\n\n{offer['response_text']}"
                        return offer

                    await rotate_workflow_session.execute(
                        conversation_id, expected_generation=workflow_generation
                    )
                    success_text = await _success_message(
                        llm_provider,
                        conversation_id,
                        appointment,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    return {
                        "response_text": success_text,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {"post_action_context": CREATE_APPOINTMENT_ACTION},
                    }

                if confirmed_action_type == CREATE_PATIENT_ACTION:
                    full_name = str(confirmed_payload["full_name"])
                    dni = str(confirmed_payload["dni"])
                    phone = PhoneNumber(str(confirmed_payload["phone"]))
                    email = str(confirmed_payload.get("email") or "") or None
                    obra_social_name = str(confirmed_payload.get("obra_social") or "")
                    try:
                        new_patient = await patient_gateway.create_patient(
                            full_name, dni, phone, email=email
                        )
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
                                "collected_data": {
                                    **collected_data,
                                    "stage": STAGE_AWAITING_IDENTIFICATION,
                                    "identification_full_name": None,
                                    "identification_dni": None,
                                },
                            }
                        new_patient = recovered

                    if obra_social_name:
                        agreement = await agreement_gateway.find_agreement_by_name(
                            obra_social_name
                        )
                        if agreement is not None:
                            await agreement_gateway.link_patient_agreement(
                                new_patient.id, agreement.id
                            )

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
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                    # The patient already picked their slot before
                    # identifying, so continue with that exact slot — never
                    # re-search.
                    return await _propose_selected_slot(
                        conversation_id,
                        _patient_to_primitives(new_patient),
                        collected_data,
                        state["recent_messages"],
                        state["contact_memory_summary"],
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
                            session_lost_text = await generate_or_fallback(
                                llm_provider,
                                str(conversation_id),
                                "session_lost",
                                {"situacion": "Se perdió el contexto de la conversación."},
                                _SESSION_LOST_MESSAGE,
                                state["recent_messages"],
                                state["contact_memory_summary"],
                            )
                            return {
                                "response_text": session_lost_text,
                                "response_buttons": None,
                                "requires_handoff": False,
                                "pending_action_id": None,
                                "collected_data": {},
                            }
                        offer = await _offer_slots(
                            conversation_id,
                            patient,
                            collected_data,
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                        slot_taken_notice = await generate_or_fallback(
                            llm_provider,
                            str(conversation_id),
                            "slot_taken",
                            {
                                "situacion": (
                                    "El horario que el paciente había elegido para reagendar "
                                    "se ocupó justo mientras confirmábamos, no se hizo ningún "
                                    "cambio; le vamos a mostrar horarios nuevos."
                                ),
                            },
                            _SLOT_TAKEN_MESSAGE,
                            state["recent_messages"],
                            state["contact_memory_summary"],
                        )
                        offer["response_text"] = f"{slot_taken_notice}\n\n{offer['response_text']}"
                        return offer

                    await rotate_workflow_session.execute(
                        conversation_id, expected_generation=workflow_generation
                    )
                    reschedule_success_text = await _reschedule_success_message(
                        llm_provider,
                        conversation_id,
                        rescheduled,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                    return {
                        "response_text": reschedule_success_text,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {"post_action_context": RESCHEDULE_APPOINTMENT_ACTION},
                    }

                raise AssertionError(  # pragma: no cover - impossible by construction
                    f"unsupported action_type: {confirmed_action_type}"
                )

            # An unrecognized/stale button while awaiting confirmation.
            stale_confirmation_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "confirmation_reminder",
                {
                    "situacion": (
                        "El paciente tocó un botón que no es válido en este paso; solo se "
                        "puede confirmar o cancelar tocando uno de los 2 botones vigentes."
                    ),
                },
                _CONFIRMATION_REMINDER,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": stale_confirmation_text,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_SLOT_SELECTION:
            if should_use_appointment_decision_subgraph(stage, collected_data):
                return await _delegate_to_decision_subgraph(state, collected_data)
            button_payload = state["button_payload"]
            available_slots = cast(list[AppointmentSlot], collected_data.get("available_slots", []))
            patient = cast(dict[str, object] | None, collected_data.get("patient"))
            # In the CREATE flow the patient is not identified yet at this
            # point (that now happens after picking a slot), so only the
            # RESCHEDULE flow requires one here.
            rescheduling = collected_data.get("rescheduling_appointment_id") is not None

            if not available_slots:
                # Repair a partial/stale checkpoint by walking back to the
                # nearest node that can rebuild the missing dependency instead
                # of erasing the whole workflow.
                repaired = invalidate_from(collected_data, "slot")
                if repaired.get("chosen_professional_id") is not None:
                    return await _offer_slots(
                        conversation_id,
                        patient,
                        repaired,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                specialty_id = cast(str | None, repaired.get("chosen_specialty_id"))
                if specialty_id is not None:
                    return await _offer_professionals(
                        conversation_id,
                        specialty_id,
                        str(repaired.get("chosen_specialty_name", "esa especialidad")),
                        repaired,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                return await _offer_specialties(
                    conversation_id,
                    repaired,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )

            if rescheduling and patient is None:
                # Identity is a required dependency for changing an existing
                # appointment. Re-identify without discarding the already
                # collected operational context.
                return await _begin_identification(
                    conversation_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )

            if button_payload == LIST_MORE_PAYLOAD:
                updated_page = next_page(collected_data, "slots_page")
                more_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "choose_slot",
                    {
                        "situacion": (
                            "Hay más horarios disponibles y hay que invitar al paciente a "
                            "elegir uno."
                        ),
                        "instruccion": (
                            "Le vamos a mostrar una lista de horarios debajo de tu mensaje — "
                            "NO los menciones ni los repitas, solo invitá a elegir uno."
                        ),
                    },
                    _CHOOSE_SLOT_PROMPT,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": more_text,
                    "response_buttons": None,
                    "response_list": _slots_list_message(
                        available_slots, page=updated_page, include_back=True
                    ),
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "slots_page": updated_page},
                }
            if button_payload == LIST_BACK_PAYLOAD:
                specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
                if specialty_id is not None:
                    return await _offer_professionals(
                        conversation_id,
                        specialty_id,
                        str(collected_data.get("chosen_specialty_name", "esa especialidad")),
                        invalidate_from(collected_data, "professional"),
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                return {
                    "response_text": WELCOME_TEXT,
                    "response_buttons": None,
                    "response_list": WELCOME_LIST,
                    "requires_handoff": False,
                    "pending_action_id": None,
                    "collected_data": {},
                }

            slot_id = slot_payload_id(button_payload)
            if slot_id is None:
                intent, situacion, static_message = (
                    (
                        "slot_selection_reminder",
                        (
                            "El paciente escribió texto libre pero en este paso solo se "
                            "puede elegir un horario tocando un botón."
                        ),
                        _SLOT_SELECTION_REMINDER,
                    )
                    if button_payload is None
                    else (
                        "stale_slot_selection",
                        (
                            "El paciente tocó un horario de un mensaje anterior que ya no "
                            "está vigente."
                        ),
                        _STALE_SLOT_SELECTION_MESSAGE,
                    )
                )
                message = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    intent,
                    {
                        "situacion": situacion,
                        "instruccion": (
                            "Le vamos a mostrar la lista de horarios de nuevo debajo de tu "
                            "mensaje — NO la repitas, solo invitá a elegir uno."
                        ),
                    },
                    static_message,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                page = current_page(collected_data, "slots_page")
                return {
                    "response_text": message,
                    "response_buttons": None,
                    "response_list": _slots_list_message(
                        available_slots, page=page, include_back=True
                    ),
                    "requires_handoff": False,
                }

            selected = slot_by_id(available_slots, slot_id)
            if selected is None:
                stale_slot_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "stale_slot_selection",
                    {
                        "situacion": (
                            "El paciente tocó un horario de un mensaje anterior que ya no "
                            "está vigente."
                        ),
                        "instruccion": (
                            "Le vamos a mostrar la lista de horarios de nuevo debajo de tu "
                            "mensaje — NO la repitas, solo invitá a elegir uno."
                        ),
                    },
                    _STALE_SLOT_SELECTION_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                page = current_page(collected_data, "slots_page")
                return {
                    "response_text": stale_slot_text,
                    "response_buttons": None,
                    "response_list": _slots_list_message(
                        available_slots, page=page, include_back=True
                    ),
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
            confirmation_text = await _reschedule_confirmation_message(
                llm_provider,
                conversation_id,
                selected,
                professional_names,
                state["recent_messages"],
                state["contact_memory_summary"],
            )

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
                session_lost_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "session_lost",
                    {"situacion": "Se perdió el contexto de la conversación."},
                    _SESSION_LOST_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": session_lost_text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {},
                }

            if button_payload is None or not button_payload.startswith(
                SELECT_APPOINTMENT_PAYLOAD_PREFIX
            ):
                intent, situacion, static_message = (
                    (
                        "appointment_selection_reminder",
                        (
                            "El paciente escribió texto libre pero en este paso solo se "
                            "puede elegir un turno tocando un botón."
                        ),
                        _APPOINTMENT_SELECTION_REMINDER,
                    )
                    if button_payload is None
                    else (
                        "stale_appointment_selection",
                        "El paciente tocó un turno de un mensaje anterior que ya no está vigente.",
                        _STALE_APPOINTMENT_SELECTION_MESSAGE,
                    )
                )
                message = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    intent,
                    {
                        "situacion": situacion,
                        "instruccion": (
                            "Le vamos a mostrar la lista de sus turnos de nuevo debajo de tu "
                            "mensaje — NO la repitas, solo invitá a elegir uno."
                        ),
                    },
                    static_message,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": message,
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
                stale_appointment_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "stale_appointment_selection",
                    {
                        "situacion": (
                            "El paciente tocó un turno de un mensaje anterior que ya no "
                            "está vigente."
                        ),
                        "instruccion": (
                            "Le vamos a mostrar la lista de sus turnos de nuevo debajo de tu "
                            "mensaje — NO la repitas, solo invitá a elegir uno."
                        ),
                    },
                    _STALE_APPOINTMENT_SELECTION_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": stale_appointment_text,
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
                cancel_patient = cast(dict[str, object] | None, collected_data.get("patient"))
                cancel_confirmation_text = await _cancel_confirmation_message(
                    llm_provider,
                    conversation_id,
                    selected_appointment,
                    professional_names,
                    str(cancel_patient["full_name"]) if cancel_patient else None,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": cancel_confirmation_text,
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
                        conversation_id,
                        specialty_id,
                        specialty_name,
                        collected_data,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                extra: dict[str, object] = {"chosen_professional_id": rescheduling_professional_id}
                if specialty_id:
                    extra["chosen_specialty_id"] = specialty_id
                    extra["chosen_specialty_name"] = specialty_name
                return await _offer_slots(
                    conversation_id,
                    patient,
                    {**collected_data, **extra},
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            reschedule_choice_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "reschedule_professional_choice_reminder",
                {
                    "situacion": (
                        "El paciente escribió texto libre pero en este paso solo se puede "
                        "elegir tocando uno de los 2 botones: mantener el mismo profesional "
                        "o elegir otro."
                    ),
                },
                _RESCHEDULE_PROFESSIONAL_CHOICE_REMINDER,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": reschedule_choice_text,
                "response_buttons": _RESCHEDULE_PROFESSIONAL_CHOICE_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_NO_SLOTS_CHOICE:
            if state["button_payload"] == _VIEW_OTHER_PROFESSIONALS_PAYLOAD:
                no_slots_specialty_id = cast(str, collected_data.get("chosen_specialty_id", ""))
                no_slots_specialty_name = cast(str, collected_data.get("chosen_specialty_name", ""))
                no_slots_professional_id = cast(
                    str | None, collected_data.get("chosen_professional_id")
                )
                return await _offer_professionals(
                    conversation_id,
                    no_slots_specialty_id,
                    no_slots_specialty_name,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                    exclude_professional_id=no_slots_professional_id,
                )
            no_slots_choice_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "no_slots_other_professionals_reminder",
                {
                    "situacion": (
                        "El paciente escribió texto libre pero en este paso solo se puede "
                        "elegir tocando el botón para ver otros profesionales."
                    ),
                },
                _NO_SLOTS_OTHER_PROFESSIONALS_MESSAGE,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": no_slots_choice_text,
                "response_buttons": _NO_SLOTS_CHOICE_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_NO_AVAILABILITY_CHOICE:
            # `MENU_MAIN_PAYLOAD` is already intercepted unconditionally
            # earlier in `node()` — reaching here means the tap was
            # something else (see `_STALE_TAP_MESSAGE`'s own comment).
            # Re-offer the same single valid option rather than silently
            # falling through to the generic operation-menu fallback.
            stale_tap_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "stale_tap",
                {
                    "situacion": (
                        "El paciente tocó un botón de un mensaje anterior que ya no está "
                        "vigente; hay que decírselo y ofrecerle el botón vigente de abajo."
                    ),
                },
                _STALE_TAP_MESSAGE,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": stale_tap_text,
                "response_buttons": _NO_AVAILABILITY_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_VERIFICATION_FLOW:
            flow_fields = parse_flow_response_payload(state["button_payload"])
            if flow_fields is None:
                # The patient typed something instead of using the Flow —
                # it's still open on their screen, so remind them rather
                # than falling back to guessing from free text.
                flow_reminder_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "verification_flow_reminder",
                    {
                        "situacion": (
                            "Le mandamos al paciente un formulario para completar y "
                            "escribió texto libre en vez de usarlo — todavía está abierto "
                            "en su pantalla."
                        ),
                    },
                    _FLOW_REMINDER_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": flow_reminder_text,
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
            verification_text = await _verification_confirmation_message(
                llm_provider,
                conversation_id,
                identified_patient,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": verification_text,
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
                        conversation_id,
                        patient_primitives,
                        collected_data,
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                return await _offer_appointments(
                    conversation_id,
                    patient_primitives,
                    patient_id,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
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
            verification_reminder_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "confirmation_reminder",
                {
                    "situacion": (
                        "El paciente tocó un botón que no es válido en este paso; solo se "
                        "puede confirmar o decir que no es así tocando uno de los 2 botones."
                    ),
                },
                _CONFIRMATION_REMINDER,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": verification_reminder_text,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
            }

        if stage == STAGE_AWAITING_REGISTRATION_FLOW:
            flow_fields = parse_flow_response_payload(state["button_payload"])
            if flow_fields is None:
                registration_reminder_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "registration_flow_reminder",
                    {
                        "situacion": (
                            "Le mandamos al paciente un formulario para completar y "
                            "escribió texto libre en vez de usarlo — todavía está abierto "
                            "en su pantalla."
                        ),
                    },
                    _FLOW_REMINDER_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": registration_reminder_text,
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
                    conversation_id,
                    patient_primitives,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            return await _offer_appointments(
                conversation_id,
                patient_primitives,
                new_patient.id,
                collected_data,
                state["recent_messages"],
                state["contact_memory_summary"],
            )

        if stage == STAGE_AWAITING_IDENTIFICATION:
            # CREATE cannot identify/confirm a booking if the slot dependency
            # disappeared from a partial checkpoint. Walk back and rebuild only
            # that chain; any already captured name/DNI remains in the dict.
            if (
                collected_data.get("operation") == CREATE_APPOINTMENT_ACTION
                and collected_data.get("pending_selected_slot") is None
                and (
                    collected_data.get("chosen_professional_id") is not None
                    or collected_data.get("chosen_specialty_id") is not None
                )
            ):
                if collected_data.get("chosen_professional_id") is not None:
                    patient = cast(dict[str, object] | None, collected_data.get("patient"))
                    return await _offer_slots(
                        conversation_id,
                        patient,
                        invalidate_from(collected_data, "slot"),
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )
                specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
                if specialty_id is not None:
                    return await _offer_professionals(
                        conversation_id,
                        specialty_id,
                        str(collected_data.get("chosen_specialty_name", "esa especialidad")),
                        invalidate_from(collected_data, "professional"),
                        state["recent_messages"],
                        state["contact_memory_summary"],
                    )

            remembered_full_name = cast(str | None, collected_data.get("identification_full_name"))
            remembered_dni = cast(str | None, collected_data.get("identification_dni"))
            merged_full_name, merged_dni = await _merge_identification(
                llm_provider, state["user_message"], remembered_full_name, remembered_dni
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
                # ask for obra social and mail before proposing to create a
                # new patient (this session's own brief), rather than
                # dead-ending. `phone` is never asked — it comes from this
                # WhatsApp contact's own identity (`conversation_id` is
                # `ycloud-{phone}` by construction, see
                # `IngestMessageUseCase`), never from parsed free text — the
                # created record is always provably tied to whoever is
                # actually messaging.
                new_patient_details_text = await _ask_new_patient_details_message(
                    conversation_id,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": new_patient_details_text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "stage": STAGE_AWAITING_NEW_PATIENT_DETAILS,
                        "new_patient_full_name": full_name.strip(),
                        "new_patient_dni": validated_dni.value,
                    },
                }
            patient_primitives = _patient_to_primitives(identified_patient)
            if collected_data.get("operation") == CREATE_APPOINTMENT_ACTION:
                return await _propose_selected_slot(
                    conversation_id,
                    patient_primitives,
                    collected_data,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
            return await _offer_appointments(
                conversation_id,
                patient_primitives,
                identified_patient.id,
                collected_data,
                state["recent_messages"],
                state["contact_memory_summary"],
            )

        if stage == STAGE_AWAITING_NEW_PATIENT_DETAILS:
            remembered_obra_social = cast(
                str | None, collected_data.get("new_patient_obra_social")
            )
            remembered_email = cast(str | None, collected_data.get("new_patient_email"))
            obra_social, email = _extract_new_patient_details(
                state["user_message"], remembered_obra_social, remembered_email
            )
            if obra_social is None and email is None:
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "new_patient_details_retry",
                    {
                        "situacion": (
                            "Todavía faltan la obra social y el mail para crear la ficha "
                            "del paciente."
                        ),
                        "formato_requerido": (
                            "Obra social y mail, ejemplo: OSDE, rosa@gmail.com. Incluí ese "
                            "ejemplo en tu respuesta."
                        ),
                    },
                    _NEW_PATIENT_DETAILS_NOT_UNDERSTOOD_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": collected_data,
                }
            if obra_social is None:
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "new_patient_details_missing_obra_social",
                    {
                        "situacion": (
                            "El paciente ya dio su mail, todavía falta su obra social."
                        ),
                        "formato_requerido": "Nombre de la obra social, ejemplo: OSDE.",
                    },
                    _ASK_NEW_PATIENT_OBRA_SOCIAL_ONLY_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "new_patient_email": email},
                }
            if email is None:
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "new_patient_details_missing_email",
                    {
                        "situacion": (
                            "El paciente ya dio su obra social, todavía falta su mail."
                        ),
                        "formato_requerido": "Mail, ejemplo: rosa@gmail.com.",
                    },
                    _ASK_NEW_PATIENT_EMAIL_ONLY_MESSAGE,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "new_patient_obra_social": obra_social},
                }
            new_patient_full_name = str(collected_data.get("new_patient_full_name"))
            new_patient_dni = str(collected_data.get("new_patient_dni"))
            contact_phone = PhoneNumber(str(conversation_id).removeprefix("ycloud-"))
            new_patient_payload = _new_patient_proposal_payload(
                new_patient_full_name, new_patient_dni, contact_phone, obra_social, email
            )
            pending_action = await propose_appointment.execute(
                conversation_id, CREATE_PATIENT_ACTION, new_patient_payload
            )
            await set_conversation_input_state.execute(conversation_id, SENSITIVE_CONFIRMATION)
            new_patient_text = await _new_patient_confirmation_message(
                llm_provider,
                conversation_id,
                new_patient_full_name,
                new_patient_dni,
                obra_social,
                email,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": new_patient_text,
                "response_buttons": _CONFIRM_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": pending_action.id,
                "collected_data": {**collected_data, "stage": STAGE_AWAITING_CONFIRMATION},
            }

        if stage == STAGE_AWAITING_SPECIALTY_SELECTION:
            # Fully owned by `app.agent.appointment_decision_subgraph` (PR 2)
            # — offering, pagination (`LIST_MORE`/`LIST_BACK`), valid/invalid/
            # stale `SPECIALTY:` resolution, and the browse-choice handoff on
            # a valid choice. See `should_use_appointment_decision_subgraph`'s
            # own docstring for the rollback point.
            return await _delegate_to_decision_subgraph(state, collected_data)

        if stage == STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE:
            # Fully owned by `app.agent.appointment_decision_subgraph` — the
            # "ver próximos turnos vs elegir profesional" screen a valid
            # specialty choice now lands on.
            return await _delegate_to_decision_subgraph(state, collected_data)

        if stage == STAGE_AWAITING_PROFESSIONAL_SELECTION:
            # Fully owned by `app.agent.appointment_decision_subgraph` (PR 2)
            # — same reasoning as `STAGE_AWAITING_SPECIALTY_SELECTION` above.
            return await _delegate_to_decision_subgraph(state, collected_data)

        if stage == STAGE_AWAITING_OPERATION_SELECTION:
            button_payload = state["button_payload"]
            operation = (
                _OPERATION_BY_PAYLOAD.get(button_payload) if button_payload is not None else None
            )
            if operation is None:
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "operation_selection_reminder",
                    {
                        "situacion": (
                            "El paciente escribió texto libre pero en este paso solo se "
                            "puede elegir tocando uno de los 3 botones (Sacar turno, "
                            "Reagendar, Cancelar)."
                        ),
                    },
                    _OPERATION_SELECTION_REMINDER,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": text,
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
                    conversation_id,
                    {**collected_data, "operation": operation},
                    state["recent_messages"],
                    state["contact_memory_summary"],
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
                    state["recent_messages"],
                    state["contact_memory_summary"],
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
                professional_prompt_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "choose_professional",
                    {
                        "situacion": (
                            "Hay que preguntarle con qué profesional prefiere atenderse; le "
                            "vamos a mostrar una lista para elegir."
                        ),
                        "instruccion": (
                            "Le vamos a mostrar la lista de profesionales debajo de tu mensaje "
                            "— NO los menciones ni los repitas, solo invitá a elegir uno."
                        ),
                    },
                    _CHOOSE_PROFESSIONAL_PROMPT,
                    state["recent_messages"],
                    state["contact_memory_summary"],
                )
                return {
                    "response_text": professional_prompt_text,
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
            create_context = {**collected_data, "operation": operation}
            if should_use_appointment_decision_subgraph(None, create_context):
                return await _delegate_to_decision_subgraph(state, create_context)
            return await _offer_specialties(
                conversation_id,
                create_context,
                state["recent_messages"],
                state["contact_memory_summary"],
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
                "instruccion": (
                    "Van a aparecer 3 botones debajo de tu mensaje (Sacar turno, Reagendar, "
                    "Cancelar) — cerrá el mensaje invitando a tocar uno de ellos, sin "
                    "listarlos ni repetir sus nombres."
                ),
            },
            _MAIN_MENU_RESET_MESSAGE if returned_to_main_menu else _OPERATION_MENU_MESSAGE,
            state["recent_messages"],
            state["contact_memory_summary"],
        )
        return {
            "response_text": text,
            "response_buttons": _OPERATION_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "stage": STAGE_AWAITING_OPERATION_SELECTION},
        }

    return node
