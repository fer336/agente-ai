from typing import cast

from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    match_named_professional,
    resolve_by_name,
    staffed_specialty_ids,
)
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.repositories.gateways import AppointmentGateway, SpecialtyGateway
from app.domain.value_objects.menu_payloads import (
    LIST_BACK_PAYLOAD,
    LIST_MORE_PAYLOAD,
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


def create_specialties_node(
    gateway: SpecialtyGateway,
    appointment_gateway: AppointmentGateway,
) -> AgentNode:
    """Lists the clinic's dental specialties from Dentalink (PRD.md §27.1).

    Both listing shapes are now paginated interactive LIST messages
    (WhatsApp's 10-row cap, 9 real rows + "Ver más" per page; the page
    position lives in `collected_data["specialties_page"]`/`["doctors_page"]`):

    - "¿qué especialidades tienen?" -> the catalog list, read-only, no
      stage set. `SPECIALTY:{id}` taps and "Ver más" are handled right
      here; "Volver atrás" returns to the main menu.
    - "quiero un médico general" -> that specialty's professionals list,
      plus the same `collected_data` cursor `appointment.py` uses, so the
      very next message continues the booking flow (pick a doctor ->
      slots -> identification). Without this, naming a specialty just
      re-printed the catalog forever, because this node used to be a dead
      end and the doctor flow lived only behind Turnos -> Sacar turno
      (seen live).

    Never a `PendingAction` — reaching a professional list writes nothing
    (PRD.md §18's "El MVP permitirá consultar"); the first sensitive write
    is still the confirmation `appointment.py` owns.
    """
    list_specialties = ListSpecialtiesUseCase(gateway)

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
            return {"response_text": _NO_SPECIALTIES_MESSAGE, "requires_handoff": False}

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
            specialty_name = next(
                (s.name for s in specialties if s.id == matched_professional.specialty_id),
                "esa especialidad",
            )
            return {
                "response_text": None,
                "response_buttons": None,
                "response_list": professionals_list_message(
                    [matched_professional], include_back=True
                ),
                "requires_handoff": False,
                "collected_data": {
                    **state["collected_data"],
                    "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                    "operation": CREATE_APPOINTMENT_ACTION,
                    "chosen_specialty_id": matched_professional.specialty_id,
                    "chosen_specialty_name": specialty_name,
                    "professional_options": [matched_professional],
                    "doctors_page": 0,
                },
            }

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
        professionals = await appointment_gateway.list_professionals(specialty_id=chosen.id)
        if not professionals:
            # Nothing to hand the booking flow — fall back to the plain
            # catalog rather than stranding the patient mid-flow.
            return {
                "response_text": None,
                "response_buttons": None,
                "response_list": specialties_list_message(
                    specialties, page=page, include_back=True
                ),
                "requires_handoff": False,
                "collected_data": {**collected_data, "specialties_page": page},
            }

        return {
            "response_text": None,
            "response_buttons": None,
            "response_list": professionals_list_message(professionals, include_back=True),
            "requires_handoff": False,
            "collected_data": {
                **state["collected_data"],
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "operation": CREATE_APPOINTMENT_ACTION,
                "chosen_specialty_id": chosen.id,
                "chosen_specialty_name": chosen.name,
                "professional_options": professionals,
                "doctors_page": 0,
            },
        }

    return node
