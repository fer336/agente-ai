from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.agreements.list_agreements import ListAgreementsUseCase
from app.domain.repositories.gateways import AgreementGateway

#: PRD.md §20: phrases that ask for a coverage detail (percentage/amount),
#: not just "do you work with X" — these can never be answered from a plain
#: name match and must derive to administración.
_COVERAGE_DETAIL_KEYWORDS = ("cuánto", "cuanto", "porcentaje", "%", "monto", "cubre")

#: PRD.md §20's exact required message for an unverifiable coverage question.
_DERIVE_TO_ADMIN_MESSAGE = (
    "Esta consulta necesita ser revisada por administración.\n"
    "¿Querés que te comunique con ellos?"
)


def create_agreement_node(
    gateway: AgreementGateway,
) -> AgentNode:
    """Answers obra social/prepaga questions from Dentalink's convenios list (PRD.md §18-20).

    Never a `PendingAction` — this is a read-only lookup, not a sensitive
    operation (PRD.md §18: "El MVP permitirá consultar" only). Matches
    against the clinic's own configured agreement names (fetched via
    `ListAgreementsUseCase`) found as a substring of the user's message —
    a deterministic stand-in for free-text name extraction/normalization
    (PRD.md §18's "Extraer/normalizar nombre" step), since no real LLM
    extraction is wired yet. Never invents coverage details (PRD.md §18
    last line, §20).
    """
    list_agreements = ListAgreementsUseCase(gateway)

    async def node(state: AgentState) -> dict[str, object]:
        lowered = state["user_message"].casefold()
        agreements = await list_agreements.execute()
        matched = next((a for a in agreements if a.name.casefold() in lowered), None)

        if matched is None:
            return {
                "response_text": (
                    "No encontramos esa obra social o prepaga en nuestros convenios "
                    "disponibles. ¿Podés confirmarme el nombre exacto?"
                ),
                "requires_handoff": False,
            }

        if any(keyword in lowered for keyword in _COVERAGE_DETAIL_KEYWORDS):
            return {"response_text": _DERIVE_TO_ADMIN_MESSAGE, "requires_handoff": False}

        return {
            "response_text": f"Sí, trabajamos con {matched.name}.",
            "requires_handoff": False,
        }

    return node
