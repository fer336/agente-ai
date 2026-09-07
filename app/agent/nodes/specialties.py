from app.agent.nodes.appointment import (
    CREATE_APPOINTMENT_ACTION,
    STAGE_AWAITING_PROFESSIONAL_SELECTION,
    choose_professional_prompt,
    numbered_list,
    resolve_by_name,
    staffed_specialty_ids,
)
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.repositories.gateways import AppointmentGateway, SpecialtyGateway

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

    Two shapes, decided by whether the patient actually named one:

    - "¿qué especialidades tienen?" -> the plain catalog listing, read-only,
      no stage set (same as before).
    - "quiero un médico general" -> that specialty's professionals, plus
      the same `collected_data` cursor `appointment.py` uses, so the very
      next message continues the booking flow (pick a doctor -> slots ->
      identification). Without this, naming a specialty just re-printed
      the catalog forever, because this node used to be a dead end and the
      doctor flow lived only behind Turnos -> Sacar turno (seen live).

    Never a `PendingAction` — reaching a professional list writes nothing
    (PRD.md §18's "El MVP permitirá consultar"); the first sensitive write
    is still the confirmation `appointment.py` owns.
    """
    list_specialties = ListSpecialtiesUseCase(gateway)

    async def node(state: AgentState) -> dict[str, object]:
        specialties = await list_specialties.execute()
        staffed = await staffed_specialty_ids(appointment_gateway)
        specialties = [s for s in specialties if s.id in staffed]

        if not specialties:
            return {"response_text": _NO_SPECIALTIES_MESSAGE, "requires_handoff": False}

        catalog = "Estas son nuestras especialidades:\n\n" + "\n".join(
            f"• {specialty.name}" for specialty in specialties
        )

        index = resolve_by_name(state["user_message"], [s.name for s in specialties])
        if index is None:
            return {"response_text": catalog, "requires_handoff": False}

        chosen = specialties[index]
        professionals = await appointment_gateway.list_professionals(specialty_id=chosen.id)
        if not professionals:
            # Nothing to hand the booking flow — fall back to the plain
            # catalog rather than stranding the patient mid-flow.
            return {"response_text": catalog, "requires_handoff": False}

        listing = numbered_list([professional.full_name for professional in professionals])
        return {
            "response_text": (
                f"Para {chosen.name} atienden:\n\n{listing}\n\n{choose_professional_prompt()}"
            ),
            "response_buttons": None,
            "requires_handoff": False,
            "collected_data": {
                **state["collected_data"],
                "stage": STAGE_AWAITING_PROFESSIONAL_SELECTION,
                "operation": CREATE_APPOINTMENT_ACTION,
                "chosen_specialty_id": chosen.id,
                "chosen_specialty_name": chosen.name,
                "professional_options": professionals,
            },
        }

    return node
