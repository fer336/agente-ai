from typing import cast

from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider
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
#: These 3 buttons are ALWAYS attached to the fallback reply (user
#: decision, this session's brief) regardless of what the LLM writes below
#: them — only the accompanying text varies.
_MAIN_MENU_MESSAGE = (
    "Noto que las opciones que te dimos no son las que buscás. Elegí una de estas, o si "
    "preferís hablar con administración tocá esa opción:"
)
_MAIN_MENU_BUTTONS = [
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Turnos"),
    InteractiveButton(id=MENU_SPECIALTIES_PAYLOAD, title="Especialidades"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="Administración"),
]


def create_fallback_node(llm_provider: LLMProvider) -> AgentNode:
    """Shows the main menu again for an unrecognized/low-confidence turn (PRD.md §8, §29).

    The wording is LLM-generated (this session's brief: a patient who keeps
    missing the menu should never see the exact same canned sentence twice,
    and a repeated miss should read as the bot noticing and offering
    administración, not just repeating itself) — but the 3 buttons below it
    are always the same static `_MAIN_MENU_BUTTONS`, never generated: a
    fallback's whole job is to be a reliable safety net, so the one thing
    that must never fail or drift is the patient's way back to a known
    option. `collected_data["fallback_count"]` tracks how many consecutive
    unresolved turns this conversation has had, told to the LLM so it can
    escalate tone/offer administración more directly on a repeat miss. If
    `generate_response` itself fails (timeout, auth, bad output), this node
    falls back to the static `_MAIN_MENU_MESSAGE` rather than propagating —
    unlike every other business node, a bug here has nowhere softer to land.
    """

    async def node(state: AgentState) -> dict[str, object]:
        collected_data = state["collected_data"]
        fallback_count = cast(int, collected_data.get("fallback_count", 0)) + 1

        text = await generate_or_fallback(
            llm_provider,
            state["conversation_id"],
            "fallback",
            {
                "situacion": (
                    "El paciente escribió algo que no coincide con ninguna opción "
                    "del menú principal de la clínica."
                ),
                "opciones_del_menu": ["Turnos", "Especialidades", "Administración"],
                "intentos_seguidos_sin_resolver": fallback_count,
                "si_2_o_mas_intentos": (
                    "Notá en el mensaje que ya lo intentamos antes y ofrecele con "
                    "calidez pasarlo directo con administración."
                ),
            },
            _MAIN_MENU_MESSAGE,
        )

        return {
            "response_text": text,
            "response_buttons": _MAIN_MENU_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "fallback_count": fallback_count},
        }

    return node
