import re
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
from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    INTERACTIVE_SELECTION,
    SENSITIVE_CONFIRMATION,
    SetConversationInputStateUseCase,
)
from app.application.patients.identify_patient import IdentifyPatientUseCase
from app.application.pending_actions.confirm_pending_action import ConfirmPendingActionUseCase
from app.application.pending_actions.reject_pending_action import RejectPendingActionUseCase
from app.domain.entities.appointment import Appointment
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.patient import Patient
from app.domain.exceptions.errors import (
    AppointmentSlotUnavailableError,
    InvalidConfirmationError,
    PatientAlreadyExistsError,
    PendingActionExpiredError,
)
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import AppointmentGateway, PatientGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.dni import Dni
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber

_SEARCH_WINDOW = timedelta(days=30)
_MAX_OPTIONS_SHOWN = 5

#: `collected_data["stage"]` values — this node's own multi-turn cursor
#: (PRD.md §9-14's flows). `resolve_interaction` only checks whether a
#: stage is set at all (routing any button/free-text turn straight back
#: here, PRD.md §24.2); this node alone interprets which one.
STAGE_AWAITING_OPERATION_SELECTION = "awaiting_operation_selection"
STAGE_AWAITING_IDENTIFICATION = "awaiting_identification"
STAGE_AWAITING_APPOINTMENT_SELECTION = "awaiting_appointment_selection"
STAGE_AWAITING_SLOT_SELECTION = "awaiting_slot_selection"
STAGE_AWAITING_CONFIRMATION = "awaiting_confirmation"

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

#: Button payload contract for this flow (PRD.md §6: deterministic, never
#: LLM-classified).
OPERATION_CREATE_PAYLOAD = "OPERATION_CREATE"
OPERATION_RESCHEDULE_PAYLOAD = "OPERATION_RESCHEDULE"
OPERATION_CANCEL_PAYLOAD = "OPERATION_CANCEL"
SELECT_APPOINTMENT_PAYLOAD_PREFIX = "SELECT_APPOINTMENT:"
SELECT_SLOT_PAYLOAD_PREFIX = "SELECT_SLOT:"
CONFIRM_APPOINTMENT_PAYLOAD = "CONFIRM_APPOINTMENT"
REJECT_APPOINTMENT_PAYLOAD = "REJECT_APPOINTMENT"

#: No upper bound on digit count here — `Dni` (7-8 digits) is the real
#: gatekeeper for validity. Capping this at 9 used to truncate a longer
#: run (e.g. a 10-digit typo) and leak the leftover digit into the parsed
#: name instead of the whole thing failing `Dni`'s length check cleanly.
_DNI_PATTERN = re.compile(r"(\d{6,})")

_OPERATION_MENU_MESSAGE = "¿Qué querés hacer?"
_OPERATION_SELECTION_REMINDER = "Por favor, elegí una opción tocando un botón."
_ASK_IDENTIFICATION_MESSAGE = (
    "Para coordinar un turno necesito identificarte primero.\n\n"
    "Escribime tu *nombre completo* y tu *DNI* (por ejemplo: Juan Pérez, 30123456)."
)
_IDENTIFICATION_NOT_UNDERSTOOD_MESSAGE = (
    "No pude leer bien tus datos. Escribime tu nombre completo y tu DNI juntos, "
    "por ejemplo: Juan Pérez, 30123456."
)
_PATIENT_NOT_FOUND_MESSAGE = (
    "No encontramos ningún paciente con esos datos. Revisá que el nombre y el DNI "
    "coincidan exactamente con los registrados en la clínica, y probá de nuevo."
)
_DNI_FORMAT_INVALID_MESSAGE = (
    "Ese DNI no parece válido. Escribime tu DNI solo con números "
    "(7 u 8 dígitos), por ejemplo: 30123456."
)
_NEW_PATIENT_RACE_LOST_MESSAGE = (
    "Encontramos un registro para ese DNI, pero con otro nombre. Por seguridad, "
    "escribime de nuevo tu nombre completo y tu DNI para verificarlo."
)
_NO_SLOTS_MESSAGE = (
    "No encontramos horarios disponibles en los próximos días. "
    "¿Querés que te comunique con administración?"
)
_NO_APPOINTMENTS_MESSAGE = (
    "No encontramos turnos próximos a tu nombre. "
    "¿Querés que te comunique con administración?"
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
_PROPOSAL_REJECTED_MESSAGE = "Listo, descartamos esa propuesta. ¿Necesitás algo más?"
_SLOT_TAKEN_MESSAGE = (
    "Ese horario acaba de ocuparse mientras confirmábamos. No se realizó ningún cambio. "
    "Te muestro nuevas opciones disponibles:"
)
_PROPOSAL_NO_LONGER_VALID_MESSAGE = "Esa propuesta ya no está vigente. Busquemos otro horario:"
_PROPOSAL_NOT_FOUND_MESSAGE = (
    "No encontramos esa propuesta. Empecemos de nuevo — ¿querés sacar un turno?"
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


def _parse_identification(text: str) -> tuple[str, str] | None:
    """Extracts (full_name, dni) from free text (PRD.md §32).

    Looks for a 6-9 digit run anywhere in the message and treats the rest as
    the full name — matches the format suggested to the patient
    (`_ASK_IDENTIFICATION_MESSAGE`): "Juan Pérez, 30123456".
    """
    match = _DNI_PATTERN.search(text)
    if match is None:
        return None
    dni = match.group(1)
    full_name = re.sub(r"\s+", " ", text[: match.start()] + text[match.end() :]).strip(" ,.-")
    if not full_name:
        return None
    return full_name, dni


def _resolve_identification(
    text: str, remembered_full_name: str | None
) -> tuple[str, str] | None:
    """Tries a fresh `(full_name, dni)` parse of `text` alone; if that fails
    but `text` is a bare DNI-like digit run with no name text of its own
    and a full name was already confirmed on an earlier attempt in this
    same identification stage (`remembered_full_name`), combines them
    instead of discarding the already-good name and asking for everything
    again — this session's own brief, prompted by a real conversation
    where a patient corrected just their DNI after already typing a valid
    name on the previous (DNI-format-invalid) attempt.
    """
    parsed = _parse_identification(text)
    if parsed is not None:
        return parsed
    if remembered_full_name is None:
        return None
    match = _DNI_PATTERN.search(text)
    if match is None:
        return None
    return remembered_full_name, match.group(1)


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
        "¿Confirmás que querés reservar este turno?"
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
        "¿Confirmás que querés cancelarlo?"
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
        "¿Confirmás el cambio?"
    )


def _new_patient_confirmation_message(full_name: str, dni: str) -> str:
    return (
        "No encontramos ningún paciente registrado con esos datos. "
        "¿Confirmás que querés crear tu ficha con estos datos?\n\n"
        f"Nombre: {full_name}\n"
        f"DNI: {dni}"
    )


def _new_patient_proposal_payload(
    full_name: str, dni: str, phone: PhoneNumber
) -> dict[str, object]:
    return {"full_name": full_name, "dni": dni, "phone": str(phone)}


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

    async def _cancel_follow_up(repositories: ProposalRepositories, pending_action_id: str) -> None:
        scheduled_actions = repositories.scheduled_actions
        scheduled_action = await scheduled_actions.get_by_pending_action_id(pending_action_id)
        if scheduled_action is not None:
            await scheduled_actions.transition_status(
                scheduled_action.id, from_status="scheduled", to_status="cancelled"
            )

    async def _offer_slots(
        conversation_id: ConversationId,
        patient: dict[str, object],
        collected_data: dict[str, object],
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        slots = await search_availability.execute(
            specialty_id=None,
            professional_id=None,
            date_range=DateTimeRange(now, now + _SEARCH_WINDOW),
        )
        if not slots:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": _NO_SLOTS_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {},
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
                "patient": patient,
                "available_slots": options,
                "professional_names": professional_names,
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
                "collected_data": {},
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
        collected_data = state["collected_data"]
        stage = collected_data.get("stage")

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
                    return {
                        "response_text": _PROPOSAL_NOT_FOUND_MESSAGE,
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {**collected_data, "stage": None},
                    }
                if isinstance(confirm_error, PendingActionExpiredError):
                    patient = cast(dict[str, object] | None, collected_data.get("patient"))
                    if patient is None:
                        return {
                            "response_text": _SESSION_LOST_MESSAGE,
                            "response_buttons": None,
                            "requires_handoff": False,
                            "pending_action_id": None,
                            "collected_data": {},
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
                    await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                    return {
                        "response_text": _cancel_success_message(),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {},
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

                    await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                    return {
                        "response_text": _success_message(appointment),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {},
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
                            await set_conversation_input_state.execute(
                                conversation_id, FREE_INPUT
                            )
                            return {
                                "response_text": _NEW_PATIENT_RACE_LOST_MESSAGE,
                                "response_buttons": None,
                                "requires_handoff": False,
                                "pending_action_id": None,
                                "collected_data": {**collected_data, "stage": None},
                            }
                        new_patient = recovered

                    # Only ever reached via `STAGE_AWAITING_IDENTIFICATION`
                    # proposing this action, which itself only does so when
                    # `operation == CREATE_APPOINTMENT_ACTION` — always
                    # continue into slot search, never appointment listing.
                    return await _offer_slots(
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
                                "collected_data": {},
                            }
                        offer = await _offer_slots(conversation_id, patient, collected_data)
                        offer["response_text"] = (
                            f"{_SLOT_TAKEN_MESSAGE}\n\n{offer['response_text']}"
                        )
                        return offer

                    await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
                    return {
                        "response_text": _reschedule_success_message(rescheduled),
                        "response_buttons": None,
                        "requires_handoff": False,
                        "pending_action_id": None,
                        "collected_data": {},
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
            available_slots = cast(
                list[AppointmentSlot], collected_data.get("available_slots", [])
            )
            patient = cast(dict[str, object] | None, collected_data.get("patient"))

            if not available_slots or patient is None:
                return {
                    "response_text": _SESSION_LOST_MESSAGE,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {},
                }

            if button_payload is None or not button_payload.startswith(
                SELECT_SLOT_PAYLOAD_PREFIX
            ):
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
            if rescheduling_appointment_id is not None:
                pending_action = await propose_appointment.execute(
                    conversation_id,
                    RESCHEDULE_APPOINTMENT_ACTION,
                    _reschedule_proposal_payload(rescheduling_appointment_id, selected),
                )
                confirmation_text = _reschedule_confirmation_message(selected, professional_names)
            else:
                pending_action = await propose_appointment.execute(
                    conversation_id, CREATE_APPOINTMENT_ACTION, _proposal_payload(patient, selected)
                )
                confirmation_text = _confirmation_message(selected, professional_names)

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
                    "collected_data": {},
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
                return await _offer_slots(
                    conversation_id,
                    patient,
                    {**collected_data, "rescheduling_appointment_id": str(selected_appointment.id)},
                )

            raise AssertionError(  # pragma: no cover - impossible by construction
                f"unsupported operation: {operation}"
            )

        if stage == STAGE_AWAITING_IDENTIFICATION:
            remembered_full_name = cast(
                str | None, collected_data.get("identification_full_name")
            )
            parsed = _resolve_identification(state["user_message"], remembered_full_name)
            if parsed is None:
                retry_count = cast(int, collected_data.get("identification_retry_count", 0)) + 1
                text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "identification_retry",
                    {
                        "situacion": (
                            "El paciente escribió algo, pero no pudimos identificar su "
                            "nombre completo y su DNI juntos en el mensaje."
                        ),
                        "formato_requerido": (
                            "Nombre completo y DNI en un mismo mensaje, ejemplo: "
                            "Juan Pérez, 30123456. Incluí ese ejemplo en tu respuesta."
                        ),
                        "intentos_seguidos": retry_count,
                    },
                    _IDENTIFICATION_NOT_UNDERSTOOD_MESSAGE,
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_retry_count": retry_count,
                    },
                }
            full_name, dni = parsed
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
                )
                return {
                    "response_text": text,
                    "response_buttons": None,
                    "requires_handoff": False,
                    "collected_data": {
                        **collected_data,
                        "identification_retry_count": retry_count,
                        "identification_full_name": full_name.strip(),
                    },
                }
            identified_patient = await identify_patient.execute(full_name, validated_dni.value)
            if identified_patient is None:
                if collected_data.get("operation") != CREATE_APPOINTMENT_ACTION:
                    # Rescheduling/cancelling requires an existing patient
                    # with an existing appointment — there is nothing to
                    # offer to create here.
                    return {
                        "response_text": _PATIENT_NOT_FOUND_MESSAGE,
                        "response_buttons": None,
                        "requires_handoff": False,
                    }
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
                return await _offer_slots(conversation_id, patient_primitives, collected_data)
            return await _offer_appointments(
                conversation_id, patient_primitives, identified_patient.id, collected_data
            )

        if stage == STAGE_AWAITING_OPERATION_SELECTION:
            button_payload = state["button_payload"]
            operation = (
                {
                    OPERATION_CREATE_PAYLOAD: CREATE_APPOINTMENT_ACTION,
                    OPERATION_RESCHEDULE_PAYLOAD: RESCHEDULE_APPOINTMENT_ACTION,
                    OPERATION_CANCEL_PAYLOAD: CANCEL_APPOINTMENT_ACTION,
                }.get(button_payload)
                if button_payload is not None
                else None
            )
            if operation is None:
                return {
                    "response_text": _OPERATION_SELECTION_REMINDER,
                    "response_buttons": _OPERATION_BUTTONS,
                    "requires_handoff": False,
                }
            return {
                "response_text": _ASK_IDENTIFICATION_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": {
                    **collected_data,
                    "stage": STAGE_AWAITING_IDENTIFICATION,
                    "operation": operation,
                },
            }

        return {
            "response_text": _OPERATION_MENU_MESSAGE,
            "response_buttons": _OPERATION_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "stage": STAGE_AWAITING_OPERATION_SELECTION},
        }

    return node
