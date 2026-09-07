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
#: A first miss gets a plain "no te entendí"; only a repeat one
#: offers administración.
_ESCALATE_AFTER_ATTEMPTS = 2

_MAIN_MENU_BUTTONS = [
    InteractiveButton(id=MENU_APPOINTMENT_PAYLOAD, title="Turnos"),
    InteractiveButton(id=MENU_SPECIALTIES_PAYLOAD, title="Especialidades"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="Administración"),
]

#: The clinic's own Google Maps place link (given by the clinic owner) — a
#: tap opens Maps and routes there directly. Kept as a literal constant and
#: appended verbatim, never handed to the LLM to reproduce: a model
#: "retyping" a URL risks mangling a query param or the place id, and
#: WhatsApp only linkifies an exact URL.
_CLINIC_MAPS_URL = (
    "https://www.google.com/maps/place/Smiling+Pilar/@-34.437762,-58.7943606,17z/data="
    "!3m1!4b1!4m12!1m5!8m4!1e2!2s104198081147178470610!3m1!1e1!3m5!1s0x95bc9f5dadc0c77f:"
    "0x7773e52613d59177!8m2!3d-34.437762!4d-58.7917857!16s%2Fg%2F11rtqc418z"
    "?hl=es-419&entry=ttu&g_ep=EgoyMDI2MDkwMi4wIKXMDSoASAFQAw%3D%3D"
)
_LOCATION_FALLBACK_MESSAGE = "Así llegás a la clínica, tocá para abrir el mapa:"
#: Free-text triggers for "where are you / how do I get there" — same
#: substring-match idiom `agreement.py` uses for coverage-detail keywords.
_LOCATION_KEYWORDS = (
    "ubicacion",
    "ubicación",
    "donde queda",
    "dónde queda",
    "donde quedan",
    "donde estan",
    "dónde están",
    "direccion",
    "dirección",
    "como llego",
    "cómo llego",
    "como llegar",
    "cómo llegar",
)


def _asks_for_location(text: str) -> bool:
    lowered = text.casefold()
    return any(keyword in lowered for keyword in _LOCATION_KEYWORDS)


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

        if _asks_for_location(state["user_message"]):
            # Checked before `pending_answer`: the model's own free-text
            # "question" answer might describe an address from memory
            # (or nothing at all) instead of the clinic's real, verified
            # link — this always wins when the patient is asking to get
            # there, LLM answer or not.
            intro = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "location",
                {
                    "situacion": "El paciente pregunta dónde queda la clínica o cómo llegar.",
                    "tono": (
                        "Cordial y breve. No escribas la dirección en texto — el link de "
                        "Maps que se agrega después ya la resuelve."
                    ),
                },
                _LOCATION_FALLBACK_MESSAGE,
            )
            remaining = {k: v for k, v in collected_data.items() if k != "pending_answer"}
            return {
                "response_text": f"{intro}\n{_CLINIC_MAPS_URL}",
                "response_buttons": None,
                "requires_handoff": False,
                "collected_data": remaining,
            }

        pending_answer = collected_data.get("pending_answer")
        if isinstance(pending_answer, str) and pending_answer.strip():
            # `resolve_interaction` already had the model answer a genuine
            # question, so there is nothing to be confused about — deliver
            # it, keep the menu as a way forward, and do NOT count this
            # turn as a failed one.
            remaining = {k: v for k, v in collected_data.items() if k != "pending_answer"}
            return {
                "response_text": pending_answer,
                "response_buttons": _MAIN_MENU_BUTTONS,
                "requires_handoff": False,
                "collected_data": remaining,
            }

        fallback_count = cast(int, collected_data.get("fallback_count", 0)) + 1

        context: dict[str, object] = {
            "situacion": (
                "El paciente escribió algo que no coincide con ninguna opción "
                "del menú principal de la clínica."
            ),
            "opciones_del_menu": ["Turnos", "Especialidades", "Administración"],
            "intentos_seguidos_sin_resolver": fallback_count,
        }
        if fallback_count >= _ESCALATE_AFTER_ATTEMPTS:
            # Only ever added on a REPEAT miss. Handing this instruction to
            # the model on every turn made a patient's very first "Hola"
            # come back as "ya intentamos un par de veces..." — the model
            # follows the instruction whether or not it actually applies.
            context["instruccion_extra"] = (
                "Notá en el mensaje que ya lo intentamos antes y ofrecele con "
                "calidez pasarlo directo con administración."
            )

        text = await generate_or_fallback(
            llm_provider,
            state["conversation_id"],
            "fallback",
            context,
            _MAIN_MENU_MESSAGE,
        )

        return {
            "response_text": text,
            "response_buttons": _MAIN_MENU_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "fallback_count": fallback_count},
        }

    return node
