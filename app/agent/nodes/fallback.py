from app.agent.state import AgentState

#: PRD.md §7's welcome menu, reused as the fallback prompt (PRD.md §8: "no
#: puede determinarlo con suficiente seguridad" -> "Mostrará nuevamente las
#: opciones principales").
_MAIN_MENU_MESSAGE = (
    "No estoy seguro de haber entendido tu consulta. Elegí una opción:\n\n"
    "📅 Turnos\n"
    "🏥 Obras sociales\n"
    "💬 Administración"
)


async def fallback_node(state: AgentState) -> dict[str, object]:
    """Shows the main menu again for an unrecognized/low-confidence turn (PRD.md §8, §29)."""
    return {"response_text": _MAIN_MENU_MESSAGE, "requires_handoff": False}
