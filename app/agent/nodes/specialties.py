from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.specialties.list_specialties import ListSpecialtiesUseCase
from app.domain.repositories.gateways import SpecialtyGateway

#: Graceful fallback for an empty/misconfigured catalog (PRD.md §18's
#: analogous "no encontramos" pattern for agreements) — never crashes, never
#: invents a specialty name.
_NO_SPECIALTIES_MESSAGE = (
    "En este momento no tenemos especialidades cargadas. "
    "¿Querés que te comunique con administración para consultarlo?"
)


def create_specialties_node(
    gateway: SpecialtyGateway,
) -> AgentNode:
    """Lists the clinic's dental specialties from Dentalink (PRD.md §27.1).

    Never a `PendingAction` — same read-only rationale as `agreement.py`'s
    own node (PRD.md §18's "El MVP permitirá consultar" only, no sensitive
    write involved). Unlike `agreement.py`, this has no free-text name to
    match against — the whole point of the "Especialidades" welcome-menu
    button is to show every configured specialty, not confirm one.
    """
    list_specialties = ListSpecialtiesUseCase(gateway)

    async def node(state: AgentState) -> dict[str, object]:
        specialties = await list_specialties.execute()

        if not specialties:
            return {"response_text": _NO_SPECIALTIES_MESSAGE, "requires_handoff": False}

        bullet_list = "\n".join(f"• {specialty.name}" for specialty in specialties)
        return {
            "response_text": f"Estas son nuestras especialidades:\n\n{bullet_list}",
            "requires_handoff": False,
        }

    return node
