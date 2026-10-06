"""Typed create-selection decision subgraph (PR 2 of the
appointment-decision-subgraph migration).

Models the first-slice create-booking path — `choose_specialty ->
choose_professional -> search_availability -> choose_slot` — as its own
compiled LangGraph graph with a narrow, ephemeral `TypedDict` state. It is
invoked from `app.agent.nodes.appointment.create_appointment_node(...)` for
a create-booking first-slice stage/context only; every other stage
(identification, verification, registration, confirmation, no-slot/
no-availability follow-up, reschedule, cancel) stays legacy-owned.

One-way dependency, same rule `appointment_selection.py` established in
PR 1: this module never imports from `app.agent.nodes.appointment` —
`appointment.py` depends on this module, never the other way around. Where
that means duplicating a small literal (a stage string, a message
constant), it is duplicated deliberately rather than creating a cycle; the
characterization tests in `tests/unit/agent/nodes/test_appointment_node.py`
and `tests/unit/agent/test_appointment_decision_subgraph.py` pin both
copies to the same observable behavior.

Read-only with respect to sensitive operations: this module never
constructs or calls `ProposeAppointmentUseCase`, `ConfirmPendingActionUseCase`,
`RejectPendingActionUseCase`, or any Dentalink write use case. A slot picked
before identity is only ever stored as `pending_selected_slot` for the
adapter to hand off to legacy `_begin_identification(...)`.
"""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, time, timedelta
from typing import Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.clinic_topics import PRESELECTED_SPECIALTY_KEY
from app.agent.handoff_offer import normalize_text
from app.agent.nodes.appointment_selection import (
    STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    current_page,
    decision_entry_node_for_stage,
    next_page,
    resolve_list_choice,
    slot_by_id,
    slot_payload_id,
    slots_list_message,
    slots_screen,
    step_slots_page,
    text_leaks_a_name,
)
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.workflow_state import invalidate_from
from app.application.appointments.search_availability import SearchAvailabilityUseCase
from app.application.appointments.search_availability_any_professional import (
    SearchAvailabilityAnyProfessionalUseCase,
)
from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    INTERACTIVE_SELECTION,
    SetConversationInputStateUseCase,
)
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.specialty import Specialty
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import AppointmentGateway, SpecialtyGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.date_time_range import DateTimeRange
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage
from app.domain.value_objects.menu_payloads import (
    CHOOSE_PROFESSIONAL_PAYLOAD,
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    LIST_PREV_PAYLOAD,
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.domain.value_objects.paginated_list import (
    specialties_list_message,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

logger = logging.getLogger(__name__)

#: Mirrors `app.agent.nodes.appointment.CREATE_APPOINTMENT_ACTION` — see
#: the module docstring's one-way-dependency note.
_CREATE_APPOINTMENT_ACTION = "create_appointment"

#: Mirrors `app.agent.nodes.appointment._SEARCH_WINDOW`/`_MAX_SLOTS_SEARCHED`
#: — Dentalink's `/v5/agendas` has no range filter, so the gateway walks one
#: sequential HTTP request per day in the window below, stopping early once
#: it has `_MAX_SLOTS_SEARCHED` slots. Confirmed live: with no cap at all, a
#: professional with heavy availability makes the search walk all 14 days
#: before replying — one real search measured 8.3s.
_SEARCH_WINDOW = timedelta(days=14)
_MAX_SLOTS_SEARCHED = 27

#: A specialty request (a list tap, a typed mention, a topic that books a
#: fixed specialty) goes straight here: the agent NEVER asks the patient to
#: choose a professional, it shows the NEXT FREE SLOTS (soonest first) across
#: ALL enabled professionals of the specialty, with date/day/time only.
#: The search is BY SPECIALTY: the gateway filters server-side
#: (`id_especialidad`) and walks forward from today with a bounded request
#: count (see `SearchAvailabilityAnyProfessionalUseCase` and
#: `search_specialty_availability`), so request volume depends neither on the
#: window length nor on the specialty's professional count. An earlier
#: version looped one `search_availability` call PER professional and hit a
#: live `429 Too Many Attempts` in production; a later one queried the whole
#: branch per day, whose 10-row responses drowned out specialties with few
#: professionals (Endodoncia, Ortodoncia).
#: The window is wide (up to 60 days) because a small specialty's first slot
#: can be 10+ days out; the walk stops as soon as the target is reached.
#: 26 slots = 3 WhatsApp list pages with bidirectional navigation (9 + 8 + 9,
#: the 10-row cap including the "Ver más"/"Volver atrás" rows); this
#: supersedes #174's single page of 10 (see `slots_screen`). The search
#: `date_range` is built from TODAY's midnight, not from `now` directly, which
#: keeps the window at exactly `_AGGREGATE_SEARCH_WINDOW.days` calendar dates.
_AGGREGATE_TARGET_SLOTS = 26
_AGGREGATE_SEARCH_WINDOW = timedelta(days=60)

#: One-shot `collected_data` flag: the caller already resolved the specialty
#: (`chosen_specialty_id`/`chosen_specialty_name`) and wants its next slots now.
SPECIALTY_SLOTS_REQUEST_KEY = "show_specialty_slots"

#: Maximum time to wait for staffed-specialty filtering before degrading
#: gracefully to showing all specialties. This prevents the first appointment
#: response from disappearing indefinitely when Dentalink is slow.
_STAFFED_SPECIALTY_TIMEOUT = timedelta(seconds=8)

#: Maximum time to wait for the specialty-catalog lookup `route_entry`'s
#: `SPECIALTY:` reroute uses to validate a payload (see its own docstring
#: comment). A sibling of `_STAFFED_SPECIALTY_TIMEOUT`, not a reuse of it:
#: the two guard unrelated calls (this one gates `route_entry` itself,
#: before any stage-specific node even runs), and keeping them separate
#: lets either be tuned without touching the other.
_SPECIALTY_REROUTE_TIMEOUT = timedelta(seconds=8)

#: Mirrors the matching message constants in `app.agent.nodes.appointment` —
#: only ever used by the specialty/professional/slot selection behavior
#: this module now owns.
_CHOOSE_SPECIALTY_PROMPT = "Para qué especialidad querés el turno? Elegí una opción de la lista:"
_SPECIALTY_NOT_UNDERSTOOD_MESSAGE = (
    "No pude identificar la especialidad. Elegí una opción de la lista:"
)
_NO_SPECIALTIES_MESSAGE = (
    "En este momento no tengo las especialidades disponibles. "
    "Querés que te comunique con administración?"
)
#: Fallback screen shown only when the aggregated "próximos turnos" search
#: finds nothing (see `_offer_any_professional_slots`). It never offers a
#: professional list (the create flow only ever shows slots): another
#: specialty, the main menu, or administration — every button title stays
#: under `InteractiveButton`'s 20-char cap and WhatsApp's 3-button cap.
_NO_SLOTS_FALLBACK_PROMPT = (
    "No encontramos turnos próximos disponibles para esa especialidad. Podés elegir "
    "otra especialidad, volver al menú principal o hablar con administración:"
)
_NO_SLOTS_FALLBACK_REMINDER = (
    "Por favor, elegí una opción tocando un botón: otra especialidad, menú principal "
    "o administración."
)
_NO_SLOTS_FALLBACK_BUTTONS = [
    InteractiveButton(id=LIST_BACK_PAYLOAD, title="Otra especialidad"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
]

_NO_SLOTS_MESSAGE = (
    "No encontramos horarios disponibles en los próximos días. "
    "Querés que te comunique con administración?"
)
_CHOOSE_SLOT_PROMPT = "Elegí un horario tocando uno de los botones:"
#: Aggregated screen (next slots of a specialty): the escape hint is appended
#: verbatim to whatever the LLM words, so it can never be dropped.
_CHOOSE_AGGREGATED_SLOT_PROMPT = "Estos son los próximos turnos disponibles. Elegí uno de la lista."
#: Shown when the professional the patient asked for has no slots and the specialty's
#: next slots are offered instead.
_NO_PROFESSIONAL_SLOTS_PROMPT = (
    "No encontramos horarios disponibles con ese profesional en los próximos días. "
    "Estos son los próximos turnos disponibles de la misma especialidad. Elegí uno de la lista."
)
_AGGREGATED_SLOT_ESCAPE_HINT = (
    "Si ninguno te sirve, escribí 'menú' para volver al inicio o 'administración' "
    "para hablar con el equipo."
)
_SLOT_SELECTION_REMINDER = (
    "Por favor, elegí uno de los horarios tocando un botón — todavía no puedo "
    "tomar la selección por texto."
)
_STALE_SLOT_SELECTION_MESSAGE = "Esa opción ya no está disponible. Elegí una de estas:"
_SESSION_LOST_MESSAGE = (
    "Se perdió el contexto de la conversación. Escribime de nuevo qué necesitás."
)

_NO_AVAILABILITY_BUTTONS = [
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]

#: After this many consecutive invalid picks from the specialty/professional
#: list, the patient is "medio desorientado" (this session's own brief) —
#: stop re-showing the same list and offer a real way out instead, mirroring
#: `app.agent.nodes.fallback`'s own escalation threshold/pattern for the
#: same reason: a retry loop with no escape hatch is worse than admitting
#: the bot isn't getting through.
_ESCALATE_AFTER_ATTEMPTS = 2
_ESCALATION_BUTTONS = [
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]

#: Entry nodes for every migrated stage that comes AFTER a specialty is
#: already chosen — see `route_entry`'s own `SPECIALTY:` interception.
#: Deliberately excludes `choose_specialty` itself (a `SPECIALTY:` tap
#: there is just the normal in-list pick, already handled) and any
#: not-yet-migrated stage (`decision_entry_node_for_stage` already maps
#: those to `None`, which is never a member here).
_NODES_AFTER_SPECIALTY_SELECTION = frozenset(
    {"choose_browse_mode", "choose_professional", "choose_slot"}
)


class AppointmentDecisionState(TypedDict, total=False):
    """Narrow, ephemeral state for the create-selection child graph.

    Never stored directly in checkpoints — `appointment.py`'s adapter
    projects `AgentState` into this shape, invokes the compiled graph, and
    converts the result back into partial `AgentState` updates.
    """

    conversation_id: str
    user_message: str
    button_payload: str | None
    recent_messages: list[dict[str, str]]
    contact_memory_summary: str | None
    pending_action_id: str | None
    collected_data: dict[str, object]

    # Internal, ephemeral routing/observability fields.
    entry_node: Literal[
        "choose_specialty",
        "choose_browse_mode",
        "choose_professional",
        "search_availability",
        "choose_slot",
        "legacy_exit",
    ]
    next_node: Literal[
        "choose_specialty",
        "choose_browse_mode",
        "choose_professional",
        "search_availability",
        "choose_slot",
        "end",
        "legacy_exit",
    ]
    decision_node: str
    exit_reason: Literal[
        "none",
        "begin_identification",
        "legacy_no_availability",
        "legacy_no_slots",
        "not_migrated",
    ]

    # Partial AgentState-compatible response fields.
    response_text: str | None
    response_buttons: list[InteractiveButton] | None
    response_list: ListMessage | None
    response_flow: FlowRequest | None
    requires_handoff: bool


async def _staffed_specialty_ids(gateway: AppointmentGateway) -> set[str]:
    """Mirrors `app.agent.nodes.appointment.staffed_specialty_ids` — see
    the module docstring's one-way-dependency note."""
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
            _staffed_specialty_ids(gateway), timeout=_STAFFED_SPECIALTY_TIMEOUT.total_seconds()
        )
    except Exception as exc:  # noqa: BLE001 -- broad catch is intentional
        logger.warning(
            "staffed_specialty_ids lookup failed or timed out; showing all specialties",
            exc_info=exc,
        )
        return None


async def _specialty_catalog_for_reroute_safe(
    list_specialties: ListSpecialtiesUseCase,
) -> list[Specialty] | None:
    """Wrapper that applies a timeout to the specialty-catalog lookup
    `route_entry`'s `SPECIALTY:` reroute uses to validate a payload.

    Mirrors `_staffed_specialty_ids_safe`'s own shape/reasoning: without
    this, a slow or failing gateway would fail the WHOLE turn here, where
    an unrecognized payload at this stage never made an external call at
    all before this reroute existed — it just took the stale/reminder
    fallback. ``None`` on timeout/failure tells `route_entry` to fall
    through to that exact same fallback, same as an unmatched id.
    """
    try:
        return await asyncio.wait_for(
            list_specialties.execute(), timeout=_SPECIALTY_REROUTE_TIMEOUT.total_seconds()
        )
    except Exception as exc:  # noqa: BLE001 -- broad catch is intentional
        logger.warning(
            "specialty_reroute_catalog_lookup failed or timed out; "
            "falling back to stale/reminder handling",
            exc_info=exc,
        )
        return None


class _DecisionNode(Protocol):
    """Callable shape LangGraph's `StateGraph.add_node` expects for this
    graph's node functions — a `Protocol`, not a plain `Callable[...]`
    alias, for the same mypy-strict-overload-resolution reason
    `app.agent.nodes.node_protocol.AgentNode` documents on its own
    docstring."""

    def __call__(self, state: AppointmentDecisionState) -> Awaitable[dict[str, object]]: ...


def _traced(node_name: str, fn: _DecisionNode) -> _DecisionNode:
    """Wraps a decision node with structured internal observability.

    Logs `conversation_id`, the legacy `collected_data["stage"]` this turn
    entered with, and the node's own `decision_node`/`exit_reason` from its
    result — internal-only attribution for diagnostics/tests, never written
    into `collected_data["stage"]` (the public checkpoint cursor stays
    whatever the node itself decided to return, untouched by this wrapper).
    """

    async def wrapped(state: AppointmentDecisionState) -> dict[str, object]:
        result = await fn(state)
        collected_data = state.get("collected_data", {})
        logger.info(
            "appointment_decision.node node=%s conversation=%s stage=%s "
            "decision_node=%s exit_reason=%s",
            node_name,
            state.get("conversation_id"),
            collected_data.get("stage"),
            result.get("decision_node", node_name),
            result.get("exit_reason"),
        )
        return result

    return wrapped


def build_appointment_decision_graph(
    *,
    appointment_gateway: AppointmentGateway,
    specialty_gateway: SpecialtyGateway,
    conversation_repository: ConversationRepository,
    llm_provider: LLMProvider,
) -> CompiledStateGraph[
    AppointmentDecisionState, None, AppointmentDecisionState, AppointmentDecisionState
]:
    """Builds and compiles the create-selection decision subgraph.

    Mirrors `create_appointment_node(...)`'s own factory shape: dependencies
    are closed over by the node functions rather than threaded through
    state, and the graph is compiled fresh (no checkpointer — this child
    graph never persists on its own; `AgentState.collected_data["stage"]`
    stays the only durable cursor, written back by the caller).
    """
    list_specialties = ListSpecialtiesUseCase(specialty_gateway)
    search_availability_use_case = SearchAvailabilityUseCase(appointment_gateway)
    search_availability_any_professional = SearchAvailabilityAnyProfessionalUseCase(
        appointment_gateway
    )
    set_conversation_input_state = SetConversationInputStateUseCase(conversation_repository)

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
                "next_node": "end",
                "decision_node": "choose_specialty",
                "exit_reason": "none",
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
                # specialty names in its own free-text reply, redundant
                # with the interactive list rendered right below it.
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
            "response_list": specialties_list_message(specialties, page=page, include_back=True),
            "requires_handoff": False,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_SPECIALTY_SELECTION,
                "specialty_options": specialties,
                "specialties_page": page,
            },
            "next_node": "end",
            "decision_node": "choose_specialty",
            "exit_reason": "none",
        }

    async def _offer_browse_choice(
        conversation_id: ConversationId,
        specialty_id: str,
        specialty_name: str,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object]:
        """Fallback screen shown only when the aggregated "próximos turnos"
        search (`_offer_any_professional_slots`) finds nothing for the
        specialty in the window: another specialty, the main menu or
        administration — never a professional list. Also re-shown verbatim
        by `choose_browse_mode` when the patient's next reply isn't one of
        these buttons."""
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "choose_browse_mode",
            {
                "situacion": (
                    "No encontramos turnos próximos para esa especialidad; hay que "
                    "ofrecerle cambiar de especialidad, volver al menú principal o hablar "
                    "con administración."
                ),
                "instruccion": (
                    "Le vamos a mostrar 3 botones debajo de tu mensaje — no los repitas "
                    "en el texto y NO ofrezcas elegir un profesional, solo planteá la pregunta."
                ),
            },
            _NO_SLOTS_FALLBACK_PROMPT,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": text,
            "response_buttons": _NO_SLOTS_FALLBACK_BUTTONS,
            "requires_handoff": False,
            "collected_data": {
                **collected_data,
                "stage": STAGE_AWAITING_SPECIALTY_BROWSE_CHOICE,
                "chosen_specialty_id": specialty_id,
                "chosen_specialty_name": specialty_name,
            },
            "next_node": "end",
            "decision_node": "choose_browse_mode",
            "exit_reason": "none",
        }

    async def choose_browse_mode(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        conversation_id = ConversationId(state["conversation_id"])
        specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
        button_payload = state.get("button_payload")
        recent_messages = state.get("recent_messages", [])
        contact_memory = state.get("contact_memory_summary")

        if specialty_id is None:
            # Defensive only, mirrors `choose_professional`'s own check —
            # a stale/corrupted checkpoint shouldn't be able to reach here
            # without a specialty already chosen.
            return await _offer_specialties(
                conversation_id, collected_data, recent_messages, contact_memory
            )
        specialty_name = str(collected_data.get("chosen_specialty_name", "esa especialidad"))

        if button_payload == LIST_BACK_PAYLOAD:
            # "Otra especialidad" — one level up, same target every other
            # specialty-level LIST_BACK already goes to.
            return await _offer_specialties(
                conversation_id,
                invalidate_from(collected_data, "specialty"),
                recent_messages,
                contact_memory,
            )
        if button_payload == CHOOSE_PROFESSIONAL_PAYLOAD:
            # A stale tap of the old "Elegir profesional" button (the create flow never
            # lists professionals any more): search the specialty's next slots again.
            return await _offer_any_professional_slots(
                conversation_id,
                specialty_id,
                specialty_name,
                collected_data,
                recent_messages,
                contact_memory,
            )

        reminder_text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "browse_mode_reminder",
            {
                "situacion": (
                    "El paciente escribió texto libre o tocó algo inválido en este paso; "
                    "solo puede elegir tocando uno de los 3 botones."
                ),
                "instruccion": (
                    "Pedile que toque uno de los botones — no los repitas en el texto."
                ),
            },
            _NO_SLOTS_FALLBACK_REMINDER,
            recent_messages,
            contact_memory,
        )
        return {
            "response_text": reminder_text,
            "response_buttons": _NO_SLOTS_FALLBACK_BUTTONS,
            "requires_handoff": False,
            "next_node": "end",
            "decision_node": "choose_browse_mode",
            "exit_reason": "none",
        }

    async def _offer_any_professional_slots(
        conversation_id: ConversationId,
        specialty_id: str,
        specialty_name: str,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
        prefetched: tuple[list[AppointmentSlot], dict[str, str]] | None = None,
        requested_professional_has_no_slots: bool = False,
    ) -> dict[str, object]:
        if prefetched is None:
            prefetched = await _search_any_professional_slots(specialty_id)
        slots, professional_names = prefetched
        if not slots:
            return await _offer_browse_choice(
                conversation_id,
                specialty_id,
                specialty_name,
                collected_data,
                recent_messages,
                contact_memory,
            )
        return await _show_slots(
            conversation_id,
            specialty_id,
            specialty_name,
            collected_data,
            recent_messages,
            contact_memory,
            slots,
            professional_names,
            requested_professional_has_no_slots=requested_professional_has_no_slots,
        )

    async def _search_any_professional_slots(
        specialty_id: str,
    ) -> tuple[list[AppointmentSlot], dict[str, str]]:
        # CLINIC-LOCAL `now`, not UTC (regression fixed here, T5a): a
        # calendar "day" only means what Dentalink itself means by one —
        # the clinic's own local date — and the gateway derives the first
        # `fecha` it asks Dentalink for from `search_range.start`. A
        # UTC-aligned `now` used to make a late clinic-local slot (e.g.
        # 22:00 in a UTC-3 clinic, already the NEXT calendar date in UTC)
        # fall in the wrong day's window, and the real gateway would then
        # ask Dentalink for the wrong `fecha` — silently losing that slot.
        # `AppointmentGateway.clinic_timezone` is exposed on the PORT
        # itself precisely so this agent-layer caller can get it without
        # importing infrastructure/`Settings` directly.
        now = datetime.now(appointment_gateway.clinic_timezone)
        # Aligned to TODAY's midnight (not `now` itself) so the window ends on
        # a calendar-day boundary: today (partial, from `now` on) plus the
        # following full days, `_AGGREGATE_SEARCH_WINDOW.days` calendar dates
        # in total, instead of `_AGGREGATE_SEARCH_WINDOW` literal hours from
        # `now` (which would touch one extra calendar date). The gateway
        # walks forward from `search_range.start`, never per day.
        today_midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
        search_range = DateTimeRange(now, today_midnight + _AGGREGATE_SEARCH_WINDOW)
        return await search_availability_any_professional.execute(
            specialty_id=specialty_id,
            date_range=search_range,
            target_slot_count=_AGGREGATE_TARGET_SLOTS,
        )

    async def _show_slots(
        conversation_id: ConversationId,
        specialty_id: str,
        specialty_name: str,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
        slots: list[AppointmentSlot],
        professional_names: dict[str, str],
        requested_professional_has_no_slots: bool = False,
    ) -> dict[str, object]:
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        static_prompt = (
            _NO_PROFESSIONAL_SLOTS_PROMPT
            if requested_professional_has_no_slots
            else _CHOOSE_AGGREGATED_SLOT_PROMPT
        )
        text = await generate_or_fallback(
            llm_provider,
            str(conversation_id),
            "no_slots_professional_next_slots"
            if requested_professional_has_no_slots
            else "choose_slot",
            {
                "situacion": (
                    "El profesional que pidió el paciente no tiene horarios en los próximos "
                    "días; le mostramos los próximos horarios libres de la misma "
                    "especialidad y hay que invitarlo a elegir uno."
                    if requested_professional_has_no_slots
                    else "Hay horarios disponibles y hay que invitar al paciente a elegir uno."
                ),
                "instruccion": (
                    "Le vamos a mostrar una lista de horarios debajo de tu mensaje — NO "
                    "los menciones ni los repitas, y NO nombres ningún profesional: el "
                    "paciente todavía no eligió con quién atenderse, eso se confirma "
                    "recién después de elegir un horario. Una sola frase corta; el aviso "
                    "para salir lo agregamos nosotros."
                ),
            },
            static_prompt,
            recent_messages,
            contact_memory,
        )
        if text_leaks_a_name(text, list(professional_names.values())):
            text = static_prompt
        text = f"{text}\n\n{_AGGREGATED_SLOT_ESCAPE_HINT}"
        # Aggregated screen: no professional is chosen, whatever a stale
        # checkpoint carried (the professional comes from the picked slot).
        collected_data = {
            key: value
            for key, value in collected_data.items()
            if key not in ("chosen_professional_id", "chosen_professional_name")
        }
        return {
            "response_text": text,
            "response_buttons": None,
            "response_list": slots_screen(slots, 0, collected_data),
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": "awaiting_slot_selection",
                "chosen_specialty_id": specialty_id,
                "chosen_specialty_name": specialty_name,
                "available_slots": slots,
                "professional_names": professional_names,
                "slots_page": 0,
            },
            "next_node": "end",
            "decision_node": "search_availability_any_professional",
            "exit_reason": "none",
        }

    async def _offer_preselected_specialty(
        conversation_id: ConversationId,
        specialty_name: str,
        collected_data: dict[str, object],
        recent_messages: list[dict[str, str]],
        contact_memory: str | None,
    ) -> dict[str, object] | None:
        """Slots of the specialty a topic books (a consulta particular -> "General"),
        skipping the specialty list. `None` means "show the normal list": the specialty
        is not in the catalog, or has no slots (never a dead end)."""
        wanted = normalize_text(specialty_name)
        catalog = await _specialty_catalog_for_reroute_safe(list_specialties)
        # Exact name, not a substring: "Odontología general" must never match "General".
        chosen = next(
            (s for s in catalog or [] if normalize_text(s.name) == wanted),
            None,
        )
        if chosen is None:
            logger.warning(
                "preselected specialty %r not found in the Dentalink catalog; "
                "showing the specialty list",
                specialty_name,
            )
            return None
        try:
            found = await _search_any_professional_slots(chosen.id)
        except Exception as exc:  # noqa: BLE001 -- external gateway boundary
            logger.warning(
                "slot search for the preselected specialty %r failed; showing the list",
                specialty_name,
                exc_info=exc,
            )
            return None
        if not found[0]:
            return None
        return await _offer_any_professional_slots(
            conversation_id,
            chosen.id,
            chosen.name,
            collected_data,
            recent_messages,
            contact_memory,
            prefetched=found,
        )

    async def route_entry(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = state.get("collected_data", {})
        stage = cast(str | None, collected_data.get("stage"))
        entry = decision_entry_node_for_stage(stage)
        button_payload = state.get("button_payload")

        # A `SPECIALTY:<id>` tap arriving at a stage AFTER specialty
        # selection — a stale specialty-list message from earlier in the
        # conversation (production bug: the patient picks a specialty, gets
        # the slot list, then taps a DIFFERENT specialty — or the SAME one
        # again — on that now-outdated specialty-list message), or simply
        # the patient changing their mind — must run a FRESH search for
        # that specialty, not whatever this stage's own payload handling
        # does with an id it doesn't recognize (`choose_slot`'s
        # `stale_slot_selection` re-send, which is what silently swallowed
        # this in production). Reschedule stays legacy-owned, untouched.
        if (
            entry in _NODES_AFTER_SPECIALTY_SELECTION
            and button_payload is not None
            and button_payload.startswith(SPECIALTY_PAYLOAD_PREFIX)
            and collected_data.get("rescheduling_appointment_id") is None
        ):
            requested_specialty_id = button_payload[len(SPECIALTY_PAYLOAD_PREFIX) :]
            specialties = await _specialty_catalog_for_reroute_safe(list_specialties)
            if specialties is not None and any(
                specialty.id == requested_specialty_id for specialty in specialties
            ):
                # Valid: reroute to `choose_specialty` with the catalog
                # repopulated (validated "the same way `choose_specialty`
                # does" — its own `resolve_list_choice` match-by-id logic
                # against `specialty_options`), so the EXACT same code path
                # a normal in-list valid pick takes runs from here:
                # `_offer_any_professional_slots` for the new specialty.
                # No selection logic duplicated.
                return {
                    "entry_node": "choose_specialty",
                    "next_node": "choose_specialty",
                    "decision_node": "route_entry",
                    "exit_reason": "none",
                    "collected_data": {
                        **invalidate_from(collected_data, "specialty"),
                        "specialty_options": specialties,
                    },
                }
            # Unknown/invalid specialty id, or the catalog lookup itself
            # timed out/failed (`specialties is None`): fall through to
            # `entry`'s own existing stale/reminder handling below,
            # unchanged.

        if collected_data.get(SPECIALTY_SLOTS_REQUEST_KEY):
            # The caller already resolved the specialty (and maybe the professional the
            # patient asked for by name): straight to the slots, whatever stage a detour
            # left behind.
            entry = (
                "search_availability"
                if collected_data.get("chosen_professional_id") is not None
                else "choose_specialty"
            )
        elif entry is None and stage is None:
            if collected_data.get("operation") == _CREATE_APPOINTMENT_ACTION:
                entry = "choose_specialty"
        if entry is None:
            return {
                "entry_node": "legacy_exit",
                "next_node": "legacy_exit",
                "decision_node": "route_entry",
                "exit_reason": "not_migrated",
            }
        return {
            "entry_node": entry,
            "next_node": entry,
            "decision_node": "route_entry",
            "exit_reason": "none",
        }

    async def choose_specialty(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        conversation_id = ConversationId(state["conversation_id"])
        options = cast(list[Specialty], collected_data.get("specialty_options", []))
        button_payload = state.get("button_payload")

        recent_messages = state.get("recent_messages", [])
        contact_memory = state.get("contact_memory_summary")

        if collected_data.pop(SPECIALTY_SLOTS_REQUEST_KEY, None):
            requested_specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
            if requested_specialty_id is not None:
                return await _offer_any_professional_slots(
                    conversation_id,
                    requested_specialty_id,
                    str(collected_data.get("chosen_specialty_name", "esa especialidad")),
                    collected_data,
                    recent_messages,
                    contact_memory,
                )

        if not options:
            preselected = collected_data.pop(PRESELECTED_SPECIALTY_KEY, None)
            if isinstance(preselected, str):
                shown = await _offer_preselected_specialty(
                    conversation_id, preselected, collected_data, recent_messages, contact_memory
                )
                if shown is not None:
                    return shown
            return await _offer_specialties(
                conversation_id, collected_data, recent_messages, contact_memory
            )

        if button_payload == LIST_MORE_PAYLOAD:
            updated_page = next_page(collected_data, "specialties_page")
            return await _offer_specialties(
                conversation_id,
                {**collected_data, "specialties_page": updated_page},
                recent_messages,
                contact_memory,
            )
        if button_payload == LIST_BACK_PAYLOAD:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": WELCOME_TEXT,
                "response_buttons": None,
                "response_list": WELCOME_LIST,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {},
                "next_node": "end",
                "decision_node": "choose_specialty",
                "exit_reason": "none",
            }

        index = resolve_list_choice(
            button_payload=button_payload,
            user_message=state.get("user_message", ""),
            payload_prefix=SPECIALTY_PAYLOAD_PREFIX,
            option_ids=[option.id for option in options],
            option_names=[option.name for option in options],
        )
        if index is None:
            retry_count = cast(int, collected_data.get("specialty_retry_count", 0)) + 1
            if retry_count >= _ESCALATE_AFTER_ATTEMPTS:
                # Re-showing the same list a patient already failed twice
                # only loops them — offer a real way out instead (this
                # session's own brief: "cuando el agente esté medio
                # desorientado, debe pedir hablar con administración").
                escalation_text = await generate_or_fallback(
                    llm_provider,
                    str(conversation_id),
                    "specialty_retry_escalation",
                    {
                        "situacion": (
                            "El paciente ya intentó elegir una especialidad un par de "
                            "veces sin éxito."
                        ),
                        "instruccion": (
                            "Notá con calidez que no se está entendiendo y ofrecele pasarlo "
                            "con administración, o volver al menú principal. Van a aparecer "
                            "esos 2 botones debajo de tu mensaje — no los repitas en el texto."
                        ),
                    },
                    _SPECIALTY_NOT_UNDERSTOOD_MESSAGE,
                    state.get("recent_messages", []),
                    state.get("contact_memory_summary"),
                )
                return {
                    "response_text": escalation_text,
                    "response_buttons": _ESCALATION_BUTTONS,
                    "requires_handoff": False,
                    "collected_data": {},
                    "next_node": "end",
                    "decision_node": "choose_specialty",
                    "exit_reason": "none",
                }
            text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "specialty_retry",
                {
                    "situacion": (
                        "El paciente no eligió una especialidad válida de la lista "
                        "interactiva que le mostramos."
                    ),
                    "instruccion": (
                        "Pedile que elija una especialidad de la lista interactiva. "
                        "No menciones números ni repitas la lista en el texto."
                    ),
                    "intentos_seguidos": retry_count,
                },
                _SPECIALTY_NOT_UNDERSTOOD_MESSAGE,
                state.get("recent_messages", []),
                state.get("contact_memory_summary"),
            )
            if text_leaks_a_name(text, [option.name for option in options]):
                text = _SPECIALTY_NOT_UNDERSTOOD_MESSAGE
            page = current_page(collected_data, "specialties_page")
            return {
                "response_text": text,
                "response_buttons": None,
                "response_list": specialties_list_message(options, page=page, include_back=True),
                "requires_handoff": False,
                "collected_data": {**collected_data, "specialty_retry_count": retry_count},
                "next_node": "end",
                "decision_node": "choose_specialty",
                "exit_reason": "none",
            }

        chosen = options[index]
        # A valid specialty selection searches and lists its soonest slots
        # across ALL enabled professionals in the SAME turn (this change —
        # most patients are new and don't know any professional by name, so
        # forcing that pick before showing a single available slot was pure
        # friction for them; the professional is auto-assigned from
        # whichever slot the patient ends up picking).
        return await _offer_any_professional_slots(
            conversation_id, chosen.id, chosen.name, collected_data, recent_messages, contact_memory
        )

    async def choose_professional(state: AppointmentDecisionState) -> dict[str, object]:
        """Legacy stage kept only for old in-flight checkpoints that stored
        `awaiting_professional_selection` with a professional list on screen. Professionals
        are never shown (create and reschedule alike): whatever arrives shows the next slots
        of the checkpoint's specialty (a "Volver atrás" still goes up to the specialty list)."""
        collected_data = dict(state.get("collected_data", {}))
        conversation_id = ConversationId(state["conversation_id"])
        specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
        recent_messages = state.get("recent_messages", [])
        contact_memory = state.get("contact_memory_summary")

        if specialty_id is None or state.get("button_payload") == LIST_BACK_PAYLOAD:
            return await _offer_specialties(
                conversation_id,
                invalidate_from(collected_data, "specialty"),
                recent_messages,
                contact_memory,
            )
        return await _offer_any_professional_slots(
            conversation_id,
            specialty_id,
            str(collected_data.get("chosen_specialty_name", "esa especialidad")),
            invalidate_from(collected_data, "professional"),
            recent_messages,
            contact_memory,
        )

    async def search_availability_node(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        collected_data.pop(SPECIALTY_SLOTS_REQUEST_KEY, None)
        conversation_id = ConversationId(state["conversation_id"])
        now = datetime.now(UTC)
        # `specialty_id` is deliberately never forwarded — same reason as
        # `appointment.py`'s own `_offer_slots`: Dentalink's `/v5/agendas`
        # never returns `id_especialidad`.
        slots = await search_availability_use_case.execute(
            specialty_id=None,
            professional_id=cast(str | None, collected_data.get("chosen_professional_id")),
            date_range=DateTimeRange(now, now + _SEARCH_WINDOW),
            limit=_MAX_SLOTS_SEARCHED,
        )
        if not slots and collected_data.get("chosen_specialty_id") is not None:
            # The requested professional has no slots, so the next slots of
            # the same specialty are offered instead — never a professional list.
            return await _offer_any_professional_slots(
                conversation_id,
                str(collected_data["chosen_specialty_id"]),
                str(collected_data.get("chosen_specialty_name", "esa especialidad")),
                collected_data,
                state.get("recent_messages", []),
                state.get("contact_memory_summary"),
                requested_professional_has_no_slots=True,
            )
        if not slots:
            await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
            no_slots_text = await generate_or_fallback(
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
                state.get("recent_messages", []),
                state.get("contact_memory_summary"),
            )
            return {
                "response_text": no_slots_text,
                "response_buttons": _NO_AVAILABILITY_BUTTONS,
                "requires_handoff": False,
                "pending_action_id": None,
                "collected_data": {
                    **collected_data,
                    "stage": "awaiting_no_availability_choice",
                },
                "next_node": "end",
                "decision_node": "search_availability",
                "exit_reason": "legacy_no_availability",
            }

        professionals = await appointment_gateway.list_professionals()
        professional_names = {p.id: p.full_name for p in professionals}
        page = current_page(collected_data, "slots_page")
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        choose_slot_text = await generate_or_fallback(
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
            state.get("recent_messages", []),
            state.get("contact_memory_summary"),
        )
        return {
            "response_text": choose_slot_text,
            "response_buttons": None,
            "response_list": slots_list_message(slots, page=page, include_back=True),
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": "awaiting_slot_selection",
                "patient": collected_data.get("patient"),
                "available_slots": slots,
                "professional_names": professional_names,
                "slots_page": page,
            },
            "next_node": "end",
            "decision_node": "search_availability",
            "exit_reason": "none",
        }

    async def choose_slot(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        if collected_data.get("rescheduling_appointment_id") is not None:
            # First slice is create-booking only — reschedule keeps its own
            # legacy handling (identity already known, proposes immediately).
            return {
                "next_node": "legacy_exit",
                "decision_node": "choose_slot",
                "exit_reason": "not_migrated",
            }

        available_slots = cast(list[AppointmentSlot], collected_data.get("available_slots", []))
        button_payload = state.get("button_payload")
        conversation_id = ConversationId(state["conversation_id"])
        recent_messages = state.get("recent_messages", [])
        contact_memory = state.get("contact_memory_summary")

        if button_payload in (LIST_MORE_PAYLOAD, LIST_PREV_PAYLOAD) and available_slots:
            # One page forward / back from the CURRENT position, clamped to the
            # ends: a stale tap on an old list re-shows the nearest valid page.
            updated_page = step_slots_page(
                available_slots,
                collected_data,
                1 if button_payload == LIST_MORE_PAYLOAD else -1,
            )
            more_text = await generate_or_fallback(
                llm_provider,
                str(conversation_id),
                "choose_slot",
                {
                    "situacion": (
                        "Hay más horarios disponibles y hay que invitar al paciente a elegir uno."
                    ),
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
                "response_text": more_text,
                "response_buttons": None,
                "response_list": slots_screen(available_slots, updated_page, collected_data),
                "requires_handoff": False,
                "collected_data": {**collected_data, "slots_page": updated_page},
                "next_node": "end",
                "decision_node": "choose_slot",
                "exit_reason": "none",
            }
        if button_payload == LIST_BACK_PAYLOAD and available_slots:
            specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
            if specialty_id is not None:
                # Back always goes up to specialty selection (the aggregated
                # list and a professional's own list alike): there is no
                # professional list to return to in the create flow.
                return await _offer_specialties(
                    conversation_id,
                    invalidate_from(collected_data, "specialty"),
                    recent_messages,
                    contact_memory,
                )

        if not available_slots:
            # Defensive only: `search_availability` is the only node that
            # ever sets `available_slots`, so this stage is not normally
            # reached with it empty. Mirrors `appointment.py`'s own
            # `_SESSION_LOST_MESSAGE` used elsewhere for lost context.
            session_lost_text = await generate_or_fallback(
                llm_provider,
                str(state["conversation_id"]),
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
                "next_node": "end",
                "decision_node": "choose_slot",
                "exit_reason": "none",
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
                    "El paciente tocó un horario de un mensaje anterior que ya no está vigente.",
                    _STALE_SLOT_SELECTION_MESSAGE,
                )
            )
            message = await generate_or_fallback(
                llm_provider,
                str(state["conversation_id"]),
                intent,
                {
                    "situacion": situacion,
                    "instruccion": (
                        "Le vamos a mostrar la lista de horarios de nuevo debajo de tu "
                        "mensaje — NO la repitas, solo invitá a elegir uno."
                    ),
                },
                static_message,
                recent_messages,
                contact_memory,
            )
            page = current_page(collected_data, "slots_page")
            return {
                "response_text": message,
                "response_buttons": None,
                "response_list": slots_screen(available_slots, page, collected_data),
                "requires_handoff": False,
                "next_node": "end",
                "decision_node": "choose_slot",
                "exit_reason": "none",
            }

        selected = slot_by_id(available_slots, slot_id)
        if selected is None:
            stale_slot_text = await generate_or_fallback(
                llm_provider,
                str(state["conversation_id"]),
                "stale_slot_selection",
                {
                    "situacion": (
                        "El paciente tocó un horario de un mensaje anterior que ya no está vigente."
                    ),
                    "instruccion": (
                        "Le vamos a mostrar la lista de horarios de nuevo debajo de tu "
                        "mensaje — NO la repitas, solo invitá a elegir uno."
                    ),
                },
                _STALE_SLOT_SELECTION_MESSAGE,
                recent_messages,
                contact_memory,
            )
            page = current_page(collected_data, "slots_page")
            return {
                "response_text": stale_slot_text,
                "response_buttons": None,
                "response_list": slots_screen(available_slots, page, collected_data),
                "requires_handoff": False,
                "next_node": "end",
                "decision_node": "choose_slot",
                "exit_reason": "none",
            }

        # Create flow only: identity is not known yet at this point (the
        # reordered flow shows a real slot before ever asking who the
        # patient is) — store the pick and hand off to legacy
        # identification. Never propose/confirm/write here.
        return {
            "collected_data": {**collected_data, "pending_selected_slot": selected},
            "next_node": "end",
            "decision_node": "choose_slot",
            "exit_reason": "begin_identification",
        }

    def _route_after_entry(state: AppointmentDecisionState) -> str:
        next_node = state.get("next_node")
        if next_node in (
            "choose_specialty",
            "choose_browse_mode",
            "choose_professional",
            "search_availability",
            "choose_slot",
        ):
            return next_node
        return END

    def _route_after_professional(state: AppointmentDecisionState) -> str:
        return "search_availability" if state.get("next_node") == "search_availability" else END

    graph: StateGraph[
        AppointmentDecisionState, None, AppointmentDecisionState, AppointmentDecisionState
    ] = StateGraph(AppointmentDecisionState)
    graph.add_node("route_entry", _traced("route_entry", route_entry))
    graph.add_node("choose_specialty", _traced("choose_specialty", choose_specialty))
    graph.add_node("choose_browse_mode", _traced("choose_browse_mode", choose_browse_mode))
    graph.add_node("choose_professional", _traced("choose_professional", choose_professional))
    graph.add_node("search_availability", _traced("search_availability", search_availability_node))
    graph.add_node("choose_slot", _traced("choose_slot", choose_slot))

    graph.add_edge(START, "route_entry")
    graph.add_conditional_edges(
        "route_entry",
        _route_after_entry,
        {
            "choose_specialty": "choose_specialty",
            "choose_browse_mode": "choose_browse_mode",
            "choose_professional": "choose_professional",
            "search_availability": "search_availability",
            "choose_slot": "choose_slot",
            END: END,
        },
    )
    # `choose_specialty`'s valid-selection branch always calls
    # `_offer_any_professional_slots` directly in the same turn (see its
    # docstring comment above) and `choose_browse_mode` only ever renders
    # its own fallback screen or inline-delegates to
    # `_offer_any_professional_slots`/`_offer_specialties` — neither node ever returns a
    # `next_node` that routes elsewhere, so both are plain unconditional exits, not routing
    # decisions.
    graph.add_edge("choose_specialty", END)
    graph.add_edge("choose_browse_mode", END)
    graph.add_conditional_edges(
        "choose_professional",
        _route_after_professional,
        {"search_availability": "search_availability", END: END},
    )
    graph.add_edge("search_availability", END)
    graph.add_edge("choose_slot", END)

    return graph.compile()
