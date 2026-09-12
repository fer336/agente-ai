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
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.appointment_selection import (
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    STAGE_AWAITING_SPECIALTY_SELECTION,
    current_page,
    decision_entry_node_for_stage,
    format_slot_option,
    next_page,
    numbered_list,
    resolve_list_choice,
    slot_button,
    slot_by_id,
    slot_payload_id,
)
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.workflow_state import invalidate_from
from app.application.appointments.search_availability import SearchAvailabilityUseCase
from app.application.conversations.set_conversation_input_state import (
    FREE_INPUT,
    INTERACTIVE_SELECTION,
    SetConversationInputStateUseCase,
)
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.entities.appointment_slot import AppointmentSlot
from app.domain.entities.professional import Professional
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
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    PROFESSIONAL_PAYLOAD_PREFIX,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.domain.value_objects.paginated_list import (
    professionals_list_message,
    specialties_list_message,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

logger = logging.getLogger(__name__)

#: Mirrors `app.agent.nodes.appointment.CREATE_APPOINTMENT_ACTION` — see
#: the module docstring's one-way-dependency note.
_CREATE_APPOINTMENT_ACTION = "create_appointment"

#: Mirrors `app.agent.nodes.appointment._SEARCH_WINDOW`/`_MAX_OPTIONS_SHOWN`.
_SEARCH_WINDOW = timedelta(days=14)
_MAX_OPTIONS_SHOWN = 3

#: Maximum time to wait for staffed-specialty filtering before degrading
#: gracefully to showing all specialties. This prevents the first appointment
#: response from disappearing indefinitely when Dentalink is slow.
_STAFFED_SPECIALTY_TIMEOUT = timedelta(seconds=8)

#: Mirrors the matching message constants in `app.agent.nodes.appointment` —
#: only ever used by the specialty/professional/slot selection behavior
#: this module now owns.
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
_NO_SLOTS_MESSAGE = (
    "No encontramos horarios disponibles en los próximos días. "
    "Querés que te comunique con administración?"
)
_CHOOSE_SLOT_PROMPT = "Elegí un horario tocando uno de los botones:"
_SLOT_SELECTION_REMINDER = (
    "Por favor, elegí uno de los horarios tocando un botón — todavía no puedo "
    "tomar la selección por texto."
)
_STALE_SLOT_SELECTION_MESSAGE = "Esa opción ya no está disponible. Elegí una de estas:"
_SESSION_LOST_MESSAGE = (
    "Se perdió el contexto de la conversación. Escribime de nuevo qué necesitás."
)

_MAIN_MENU_BUTTON = InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Volver al Menú")
_NO_AVAILABILITY_BUTTONS = [
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="Menú principal"),
]


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
        "choose_professional",
        "choose_slot",
        "legacy_exit",
    ]
    next_node: Literal[
        "choose_specialty",
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
    set_conversation_input_state = SetConversationInputStateUseCase(conversation_repository)

    async def _offer_specialties(
        conversation_id: ConversationId, collected_data: dict[str, object]
    ) -> dict[str, object]:
        specialties = await list_specialties.execute()
        staffed = await _staffed_specialty_ids(appointment_gateway)
        specialties = [s for s in specialties if s.id in staffed]
        if not specialties:
            await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
            return {
                "response_text": _NO_SPECIALTIES_MESSAGE,
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": {},
                "next_node": "end",
                "decision_node": "choose_specialty",
                "exit_reason": "none",
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = current_page(collected_data, "specialties_page")
        return {
            "response_text": _CHOOSE_SPECIALTY_PROMPT,
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
                "collected_data": {},
                "next_node": "end",
                "decision_node": "choose_professional",
                "exit_reason": "none",
            }

        await set_conversation_input_state.execute(conversation_id, FREE_INPUT)
        page = current_page(collected_data, "doctors_page")
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
            "next_node": "end",
            "decision_node": "choose_professional",
            "exit_reason": "none",
        }

    async def route_entry(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = state.get("collected_data", {})
        stage = cast(str | None, collected_data.get("stage"))
        entry = decision_entry_node_for_stage(stage)
        if entry is None and stage is None:
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

        if not options:
            return await _offer_specialties(conversation_id, collected_data)

        if button_payload == LIST_MORE_PAYLOAD:
            updated_page = next_page(collected_data, "specialties_page")
            return await _offer_specialties(
                conversation_id, {**collected_data, "specialties_page": updated_page}
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
            listing = numbered_list([option.name for option in options])
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
                state.get("recent_messages", []),
                state.get("contact_memory_summary"),
            )
            return {
                "response_text": f"{text}\n\n{listing}",
                "response_buttons": [_MAIN_MENU_BUTTON],
                "requires_handoff": False,
                "collected_data": {**collected_data, "specialty_retry_count": retry_count},
                "next_node": "end",
                "decision_node": "choose_specialty",
                "exit_reason": "none",
            }

        chosen = options[index]
        # Mirrors `_offer_specialties`' own legacy sibling: a valid specialty
        # selection renders the professional list in the SAME turn, exactly
        # as `appointment.py`'s `STAGE_AWAITING_SPECIALTY_SELECTION` handler
        # does today (`return await _offer_professionals(...)`), rather than
        # re-entering the dual-purpose `choose_professional` node — that
        # node's own "no options yet" signal means something different (a
        # stale/corrupted checkpoint), so it cannot double as "just chosen".
        return await _offer_professionals(conversation_id, chosen.id, chosen.name, collected_data)

    async def choose_professional(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        conversation_id = ConversationId(state["conversation_id"])
        professional_options = cast(
            list[Professional], collected_data.get("professional_options", [])
        )
        specialty_id = cast(str | None, collected_data.get("chosen_specialty_id"))
        button_payload = state.get("button_payload")

        if specialty_id is None:
            return await _offer_specialties(conversation_id, collected_data)
        if not professional_options:
            return await _offer_professionals(
                conversation_id,
                specialty_id,
                str(collected_data.get("chosen_specialty_name", "esa especialidad")),
                collected_data,
            )

        if button_payload == LIST_MORE_PAYLOAD:
            updated_page = next_page(collected_data, "doctors_page")
            return await _offer_professionals(
                conversation_id,
                specialty_id,
                str(collected_data.get("chosen_specialty_name", "")),
                {**collected_data, "doctors_page": updated_page},
            )
        if button_payload == LIST_BACK_PAYLOAD:
            return await _offer_specialties(
                conversation_id, invalidate_from(collected_data, "specialty")
            )

        index = resolve_list_choice(
            button_payload=button_payload,
            user_message=state.get("user_message", ""),
            payload_prefix=PROFESSIONAL_PAYLOAD_PREFIX,
            option_ids=[option.id for option in professional_options],
            option_names=[option.full_name for option in professional_options],
        )
        if index is None:
            retry_count = cast(int, collected_data.get("professional_retry_count", 0)) + 1
            listing = numbered_list([option.full_name for option in professional_options])
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
                state.get("recent_messages", []),
                state.get("contact_memory_summary"),
            )
            return {
                "response_text": f"{text}\n\n{listing}",
                "response_buttons": [_MAIN_MENU_BUTTON],
                "requires_handoff": False,
                "collected_data": {**collected_data, "professional_retry_count": retry_count},
                "next_node": "end",
                "decision_node": "choose_professional",
                "exit_reason": "none",
            }

        chosen_professional = professional_options[index]
        return {
            "collected_data": {
                **collected_data,
                "chosen_professional_id": chosen_professional.id,
                "chosen_professional_name": chosen_professional.full_name,
            },
            "next_node": "search_availability",
            "decision_node": "choose_professional",
            "exit_reason": "none",
        }

    async def search_availability_node(state: AppointmentDecisionState) -> dict[str, object]:
        collected_data = dict(state.get("collected_data", {}))
        conversation_id = ConversationId(state["conversation_id"])
        now = datetime.now(UTC)
        # `specialty_id` is deliberately never forwarded — same reason as
        # `appointment.py`'s own `_offer_slots`: Dentalink's `/v5/agendas`
        # never returns `id_especialidad`.
        slots = await search_availability_use_case.execute(
            specialty_id=None,
            professional_id=cast(str | None, collected_data.get("chosen_professional_id")),
            date_range=DateTimeRange(now, now + _SEARCH_WINDOW),
            limit=_MAX_OPTIONS_SHOWN,
        )
        if not slots:
            await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
            return {
                "response_text": _NO_SLOTS_MESSAGE,
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

        options = slots[:_MAX_OPTIONS_SHOWN]
        professionals = await appointment_gateway.list_professionals()
        professional_names = {p.id: p.full_name for p in professionals}
        lines = "\n".join(format_slot_option(slot, professional_names) for slot in options)
        await set_conversation_input_state.execute(conversation_id, INTERACTIVE_SELECTION)
        return {
            "response_text": f"{_CHOOSE_SLOT_PROMPT}\n\n{lines}",
            "response_buttons": [slot_button(slot) for slot in options],
            "requires_handoff": False,
            "pending_action_id": None,
            "collected_data": {
                **collected_data,
                "stage": "awaiting_slot_selection",
                "patient": collected_data.get("patient"),
                "available_slots": options,
                "professional_names": professional_names,
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
        professional_names = cast(dict[str, str], collected_data.get("professional_names", {}))

        if not available_slots:
            # Defensive only: `search_availability` is the only node that
            # ever sets `available_slots`, so this stage is not normally
            # reached with it empty. Mirrors `appointment.py`'s own
            # `_SESSION_LOST_MESSAGE` used elsewhere for lost context.
            return {
                "response_text": _SESSION_LOST_MESSAGE,
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
            message = (
                _SLOT_SELECTION_REMINDER
                if button_payload is None
                else _STALE_SLOT_SELECTION_MESSAGE
            )
            lines = "\n".join(
                format_slot_option(slot, professional_names) for slot in available_slots
            )
            return {
                "response_text": f"{message}\n\n{lines}",
                "response_buttons": [slot_button(slot) for slot in available_slots],
                "requires_handoff": False,
                "next_node": "end",
                "decision_node": "choose_slot",
                "exit_reason": "none",
            }

        selected = slot_by_id(available_slots, slot_id)
        if selected is None:
            lines = "\n".join(
                format_slot_option(slot, professional_names) for slot in available_slots
            )
            return {
                "response_text": f"{_STALE_SLOT_SELECTION_MESSAGE}\n\n{lines}",
                "response_buttons": [slot_button(slot) for slot in available_slots],
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
        if next_node in ("choose_specialty", "choose_professional", "choose_slot"):
            return next_node
        return END

    def _route_after_professional(state: AppointmentDecisionState) -> str:
        return "search_availability" if state.get("next_node") == "search_availability" else END

    graph: StateGraph[
        AppointmentDecisionState, None, AppointmentDecisionState, AppointmentDecisionState
    ] = StateGraph(AppointmentDecisionState)
    graph.add_node("route_entry", _traced("route_entry", route_entry))
    graph.add_node("choose_specialty", _traced("choose_specialty", choose_specialty))
    graph.add_node("choose_professional", _traced("choose_professional", choose_professional))
    graph.add_node(
        "search_availability", _traced("search_availability", search_availability_node)
    )
    graph.add_node("choose_slot", _traced("choose_slot", choose_slot))

    graph.add_edge(START, "route_entry")
    graph.add_conditional_edges(
        "route_entry",
        _route_after_entry,
        {
            "choose_specialty": "choose_specialty",
            "choose_professional": "choose_professional",
            "choose_slot": "choose_slot",
            END: END,
        },
    )
    # `choose_specialty`'s valid-selection branch always calls
    # `_offer_professionals` directly in the same turn (see its docstring
    # comment above) and never returns `next_node="choose_professional"`,
    # so this edge is a plain unconditional exit, not a routing decision.
    graph.add_edge("choose_specialty", END)
    graph.add_conditional_edges(
        "choose_professional",
        _route_after_professional,
        {"search_availability": "search_availability", END: END},
    )
    graph.add_edge("search_availability", END)
    graph.add_edge("choose_slot", END)

    return graph.compile()
