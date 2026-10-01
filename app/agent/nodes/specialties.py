from typing import cast

from app.agent.appointment_decision_subgraph import (
    SPECIALTY_SLOTS_REQUEST_KEY,
    AppointmentDecisionState,
    build_appointment_decision_graph,
)
from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    match_named_professional,
    resolve_by_name,
    staffed_specialty_ids,
)
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import AppointmentGateway, SpecialtyGateway
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
    SPECIALTY_PAYLOAD_PREFIX,
)
from app.domain.value_objects.paginated_list import (
    professionals_list_message,
    specialties_list_message,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST

#: Graceful fallback for an empty/misconfigured catalog (PRD.md §18's
#: analogous "no encontramos" pattern for agreements) — never crashes, never
#: invents a specialty name.
_NO_SPECIALTIES_MESSAGE = (
    "En este momento no tenemos especialidades cargadas. "
    "Querés que te comunique con administración para consultarlo?"
)


def _has_booking_context(button_payload: str | None, collected_data: dict[str, object]) -> bool:
    """True when this turn already carries explicit create-booking intent
    or context, per the browse-vs-booking separation spec requirement.

    `SPECIALTIES_NODE` only ever runs on a `intent == "specialties"` turn
    (read-only catalog browsing, `app/agent/graph.py`'s own routing) — a
    named specialty or professional match found in that turn's free text
    must not silently start (or continue) a booking on its own unless one
    of these explicit signals is also present:

    - `MENU_APPOINTMENT_PAYLOAD`/`OPERATION_CREATE_PAYLOAD`: the patient
      tapped a booking row directly (defensive — resolve_interaction.py
      already routes these to `intent="appointment"` before this node
      would ever see them, but the check stays cheap and correct either
      way).
    - `collected_data["operation"] == CREATE_APPOINTMENT_ACTION`: an
      already-resolved booking operation from a prior turn.
    - `collected_data["operation_mention"] == "create"`: the LLM's own
      understanding of THIS turn's free text already read it as booking
      language (e.g. "quiero un turno con..."), carried in by
      `resolve_interaction.py`'s `_carried_understanding(...)` even while
      routing the turn's `intent` to "specialties" for display purposes.
    - `collected_data["stage"] is not None`: an appointment flow is
      already active (a temporary informational detour into this node,
      PRD/design's "must not clear collected_data['stage']" rule) — the
      booking cursor that's already there is real context, not a fresh
      browse.
    """
    if button_payload in (MENU_APPOINTMENT_PAYLOAD, OPERATION_CREATE_PAYLOAD):
        return True
    if collected_data.get("operation") == CREATE_APPOINTMENT_ACTION:
        return True
    if collected_data.get("operation_mention") == "create":
        return True
    return collected_data.get("stage") is not None


def create_specialties_node(
    gateway: SpecialtyGateway,
    appointment_gateway: AppointmentGateway,
    llm_provider: LLMProvider,
    conversation_repository: ConversationRepository,
) -> AgentNode:
    """Lists the clinic's dental specialties from Dentalink (PRD.md §27.1).

    Both listing shapes are now paginated interactive LIST messages
    (WhatsApp's 10-row cap, 9 real rows + "Ver más" per page; the page
    position lives in `collected_data["specialties_page"]`/`["doctors_page"]`):

    - "¿qué especialidades tienen?" -> the catalog list, read-only, no
      stage set. `SPECIALTY:{id}` taps and "Ver más" are handled right
      here; "Volver atrás" returns to the main menu.
    - "quiero un médico general" -> that specialty's NEXT 10 FREE SLOTS
      (the create flow never shows a professional list), plus the same
      `collected_data` cursor `appointment.py` uses, so the very next
      message continues the booking flow (pick a slot -> identification).
      Without this, naming a specialty just re-printed the catalog forever,
      because this node used to be a dead end (seen live).

    Never a `PendingAction` — reaching a professional list writes nothing
    (PRD.md §18's "El MVP permitirá consultar"); the first sensitive write
    is still the confirmation `appointment.py` owns.
    """
    list_specialties = ListSpecialtiesUseCase(gateway)
    decision_graph = build_appointment_decision_graph(
        appointment_gateway=appointment_gateway,
        specialty_gateway=gateway,
        conversation_repository=conversation_repository,
        llm_provider=llm_provider,
    )

    async def _show_next_slots(
        state: AgentState, collected_data: dict[str, object]
    ) -> dict[str, object]:
        """Hands a booking turn with a resolved specialty to the decision subgraph, which
        replies with the specialty's next free slots (never a professional list)."""
        decision_state: AppointmentDecisionState = {
            "conversation_id": state["conversation_id"],
            "user_message": state["user_message"],
            "button_payload": state["button_payload"],
            "recent_messages": state["recent_messages"],
            "contact_memory_summary": state["contact_memory_summary"],
            "pending_action_id": state.get("pending_action_id"),
            "collected_data": {
                **collected_data,
                "operation": CREATE_APPOINTMENT_ACTION,
                SPECIALTY_SLOTS_REQUEST_KEY: True,
            },
        }
        result = await decision_graph.ainvoke(decision_state)
        updates: dict[str, object] = {
            "response_text": result.get("response_text"),
            "response_buttons": result.get("response_buttons"),
            "response_list": result.get("response_list"),
            "requires_handoff": result.get("requires_handoff", False),
            "collected_data": result.get("collected_data"),
        }
        if "pending_action_id" in result:
            updates["pending_action_id"] = result["pending_action_id"]
        return updates

    async def node(state: AgentState) -> dict[str, object]:
        button_payload = state["button_payload"]
        collected_data = state["collected_data"]

        if button_payload == LIST_BACK_PAYLOAD:
            # Back from the catalog = back to the main menu.
            return {
                "response_text": None,
                "response_buttons": None,
                "response_list": WELCOME_LIST,
                "requires_handoff": False,
                "collected_data": {},
            }

        specialties = await list_specialties.execute()
        staffed = await staffed_specialty_ids(appointment_gateway)
        specialties = [s for s in specialties if s.id in staffed]

        if not specialties:
            text = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "no_specialties",
                {"situacion": "No hay especialidades cargadas en este momento."},
                _NO_SPECIALTIES_MESSAGE,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {"response_text": text, "requires_handoff": False}

        # Pagination: the catalog path re-renders on LIST_MORE taps.
        page = cast(int, collected_data.get("specialties_page", 0) or 0)
        if button_payload == LIST_MORE_PAYLOAD:
            page += 1

        index = resolve_by_name(state["user_message"], [s.name for s in specialties])
        row_tap_index = (
            next(
                (
                    i
                    for i, s in enumerate(specialties)
                    if button_payload == f"{SPECIALTY_PAYLOAD_PREFIX}{s.id}"
                ),
                None,
            )
            if button_payload is not None
            else None
        )
        if index is None and row_tap_index is None:
            matched_professional = await match_named_professional(
                appointment_gateway, state["user_message"]
            )
            if matched_professional is None:
                # Plain catalog screen (page 0 on a fresh ask, `page` on a
                # Ver más tap).
                return {
                    "response_text": None,
                    "response_buttons": None,
                    "response_list": specialties_list_message(
                        specialties, page=page, include_back=True
                    ),
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "specialties_page": page},
                }
            if not _has_booking_context(button_payload, collected_data):
                # Browse-only: show who matches, but never start a booking
                # on a plain catalog turn (spec's "Browse specialty without
                # booking context" requirement).
                return {
                    "response_text": None,
                    "response_buttons": None,
                    "response_list": professionals_list_message(
                        [matched_professional], include_back=True
                    ),
                    "requires_handoff": False,
                    "collected_data": {**collected_data, "specialties_page": page},
                }
            specialty_name = next(
                (s.name for s in specialties if s.id == matched_professional.specialty_id),
                "esa especialidad",
            )
            # Booking: straight to that professional's slots (never a professional list); with
            # no slots the subgraph offers the specialty's next slots instead.
            return await _show_next_slots(
                state,
                {
                    **collected_data,
                    "chosen_specialty_id": matched_professional.specialty_id,
                    "chosen_specialty_name": specialty_name,
                    "chosen_professional_id": matched_professional.id,
                    "chosen_professional_name": matched_professional.full_name,
                },
            )

        chosen_index = row_tap_index if row_tap_index is not None else index
        if chosen_index is None:
            return {
                "response_text": None,
                "response_buttons": None,
                "response_list": specialties_list_message(
                    specialties, page=page, include_back=True
                ),
                "requires_handoff": False,
                "collected_data": {**collected_data, "specialties_page": page},
            }
        chosen = specialties[int(chosen_index)]
        if _has_booking_context(button_payload, collected_data):
            # Never a professional list in the create flow: the specialty alone shows its
            # next free slots across all of its professionals.
            return await _show_next_slots(
                state,
                {
                    **collected_data,
                    "chosen_specialty_id": chosen.id,
                    "chosen_specialty_name": chosen.name,
                },
            )
        professionals = await appointment_gateway.list_professionals(specialty_id=chosen.id)
        if not professionals:
            # Nothing to show for this specialty — fall back to the plain
            # catalog rather than stranding the patient.
            return {
                "response_text": None,
                "response_buttons": None,
                "response_list": specialties_list_message(
                    specialties, page=page, include_back=True
                ),
                "requires_handoff": False,
                "collected_data": {**collected_data, "specialties_page": page},
            }

        # Browse-only: a row tap or a named specialty found in plain catalog free text just
        # shows that specialty's professionals — it never starts a booking on its own
        # (spec's "Browse specialty without booking context" requirement). This read-only
        # listing is deliberately kept: it is catalog information, not the create flow.
        return {
            "response_text": None,
            "response_buttons": None,
            "response_list": professionals_list_message(professionals, include_back=True),
            "requires_handoff": False,
            "collected_data": {**collected_data, "specialties_page": page},
        }

    return node
