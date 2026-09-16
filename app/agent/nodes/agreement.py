from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.agreements.list_agreements import ListAgreementsUseCase
from app.domain.repositories.gateways import AgreementGateway
from app.domain.repositories.llm_provider import LLMProvider

#: PRD.md §20: phrases that ask for a coverage detail (percentage/amount),
#: not just "do you work with X" — these can never be answered from a plain
#: name match and must derive to administración.
_COVERAGE_DETAIL_KEYWORDS = ("cuánto", "cuanto", "porcentaje", "%", "monto", "cubre")

#: PRD.md §20's exact required message for an unverifiable coverage
#: question — this specific wording is a documented product requirement
#: (the PRD spells it out verbatim as what must be sent), not a stylistic
#: default, so it deliberately stays hardcoded rather than going through
#: the LLM like every other message in this codebase (user's own call,
#: after this conflict was flagged).
_DERIVE_TO_ADMIN_MESSAGE = (
    "Esta consulta necesita ser revisada por administración.\n"
    "Querés que te comunique con ellos?"
)

#: `_NOT_FOUND_MESSAGE`/the confirmed-match reply below are NOT PRD-mandated
#: wording (only `_DERIVE_TO_ADMIN_MESSAGE` above is) — these are the
#: `generate_or_fallback` static fallback for when the LLM call itself
#: fails.
_NOT_FOUND_MESSAGE = (
    "No encontramos esa obra social o prepaga en nuestros convenios "
    "disponibles. Podés confirmarme el nombre exacto?"
)


def create_agreement_node(
    gateway: AgreementGateway,
    llm_provider: LLMProvider,
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
            text = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "agreement_not_found",
                {
                    "situacion": (
                        "El paciente preguntó por una obra social o prepaga que no está "
                        "en nuestros convenios disponibles."
                    ),
                    "instruccion": "Pedile que confirme el nombre exacto.",
                },
                _NOT_FOUND_MESSAGE,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": text,
                "requires_handoff": False,
            }

        if any(keyword in lowered for keyword in _COVERAGE_DETAIL_KEYWORDS):
            return {"response_text": _DERIVE_TO_ADMIN_MESSAGE, "requires_handoff": False}

        text = await generate_or_fallback(
            llm_provider,
            state["conversation_id"],
            "agreement_found",
            {
                "situacion": (
                    "El paciente preguntó por una obra social o prepaga que sí está "
                    "en convenio."
                ),
                "convenio": matched.name,
                "instruccion": "Confirmá que sí trabajan con ese convenio, mencionando su nombre.",
            },
            f"Sí, trabajamos con {matched.name}.",
            state["recent_messages"],
            state["contact_memory_summary"],
        )
        return {
            "response_text": text,
            "requires_handoff": False,
        }

    return node
