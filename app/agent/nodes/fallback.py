from app.agent.state import AgentState
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_APPOINTMENT_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
)

#: PRD.md §7's welcome menu, reused as the fallback prompt (PRD.md §8: "no
#: puede determinarlo con suficiente seguridad" -> "Mostrará nuevamente las
#: opciones principales"). Real tappable buttons, same payload ids as
#: `IngestMessageUseCase._WELCOME_BUTTONS` — a button tap always carries a
#: known intent (PRD.md §6), unlike free text the patient could mistype.
_MAIN_MENU_MESSAGE = "No estoy seguro de haber entendido tu consulta. Elegí una opción:"
_MAIN_MENU_BUTTONS = [
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Turnos"),
    InteractiveButton(id=MENU_SPECIALTIES_PAYLOAD, title="Especialidades"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="Administración"),
]


async def fallback_node(state: AgentState) -> dict[str, object]:
    """Shows the main menu again for an unrecognized/low-confidence turn (PRD.md §8, §29)."""
    return {
        "response_text": _MAIN_MENU_MESSAGE,
        "response_buttons": _MAIN_MENU_BUTTONS,
        "requires_handoff": False,
    }
