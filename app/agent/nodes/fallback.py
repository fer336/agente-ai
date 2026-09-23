from typing import cast

from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, OPERATION_CREATE_PAYLOAD

#: A confused patient gets exactly two ways forward (user decision, this
#: session's brief): book directly (`OPERATION_CREATE_PAYLOAD`, the same
#: payload `WELCOME_LIST`'s "📅 Agendar una cita" row carries — a tap opens
#: the specialty list straight away) or talk to a human
#: (`MENU_ADMIN_PAYLOAD`). The legacy "Turnos"/"Especialidades" buttons are
#: gone — both were one extra tap away from a flow this reply can now open
#: directly. `MENU_APPOINTMENT_PAYLOAD`/`MENU_SPECIALTIES_PAYLOAD` stay
#: routable in `resolve_interaction.py` regardless (old chat history can
#: still be tapped), this reply just never sends them again.
_CONFUSED_PATIENT_MESSAGE = (
    "Noto que las opciones que te dimos no son las que buscás. Tocá 📅 Agendar una cita si "
    "querés sacar un turno, o 💬 Administración si preferís que te ayude alguien del consultorio."
)
#: A first miss gets a plain "no te entendí"; only a repeat one
#: offers administración.
_ESCALATE_AFTER_ATTEMPTS = 2

_CONFUSED_PATIENT_BUTTONS = [
    InteractiveButton(id=OPERATION_CREATE_PAYLOAD, title="📅 Agendar una cita"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
]

#: The clinic's real coordinates/address (given by the clinic owner) —
#: sent as a native WhatsApp location card (a tap opens Maps directly),
#: never handed to the LLM to describe: it has no reliable way to know
#: the real address, and a model "retyping" coordinates risks a mangled
#: pin.
_CLINIC_NAME = "Smiling Pilar"
_CLINIC_LATITUDE = -34.437762
_CLINIC_LONGITUDE = -58.7917857
_CLINIC_ADDRESS = "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires"
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
    """Offers a direct way out for an unrecognized/low-confidence turn (PRD.md §8, §29).

    The wording is LLM-generated (this session's brief: a patient who keeps
    missing the menu should never see the exact same canned sentence twice,
    and a repeated miss should read as the bot noticing and offering
    administración, not just repeating itself) — but the 2 buttons below it
    are always the same static `_CONFUSED_PATIENT_BUTTONS`, never generated: a
    fallback's whole job is to be a reliable safety net, so the one thing
    that must never fail or drift is the patient's way back to a known
    option. `collected_data["fallback_count"]` tracks how many consecutive
    unresolved turns this conversation has had, told to the LLM so it can
    escalate tone/offer administración more directly on a repeat miss. If
    `generate_response` itself fails (timeout, auth, bad output), this node
    falls back to the static `_CONFUSED_PATIENT_MESSAGE` rather than
    propagating — unlike every other business node, a bug here has nowhere
    softer to land.
    """

    async def node(state: AgentState) -> dict[str, object]:
        collected_data = state["collected_data"]

        if _asks_for_location(state["user_message"]):
            # Checked before `pending_answer`: the model's own free-text
            # "question" answer might describe an address from memory (or
            # nothing at all) instead of the clinic's real, verified
            # location — this always wins when the patient is asking to
            # get there, LLM answer or not. A native location card needs
            # no accompanying text (WhatsApp shows name/address on the
            # card itself), so this is the one reply with no LLM step.
            remaining = {k: v for k, v in collected_data.items() if k != "pending_answer"}
            return {
                "response_text": None,
                "response_buttons": None,
                "response_location": LocationRequest(
                    latitude=_CLINIC_LATITUDE,
                    longitude=_CLINIC_LONGITUDE,
                    name=_CLINIC_NAME,
                    address=_CLINIC_ADDRESS,
                ),
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
                "response_buttons": _CONFUSED_PATIENT_BUTTONS,
                "requires_handoff": False,
                "collected_data": remaining,
            }

        fallback_count = cast(int, collected_data.get("fallback_count", 0)) + 1

        context: dict[str, object] = {
            "situacion": (
                "El paciente escribió algo que no coincide con ninguna opción "
                "del menú principal de la clínica."
            ),
            "opciones_del_menu": ["📅 Agendar una cita", "💬 Administración"],
            "instruccion": (
                "Van a aparecer 2 botones debajo de tu mensaje: uno para agendar una cita y "
                "otro para hablar con alguien del consultorio — cerrá el mensaje invitando a "
                "tocar uno de ellos, sin listarlos ni repetir sus nombres."
            ),
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
            _CONFUSED_PATIENT_MESSAGE,
            state["recent_messages"],
            state["contact_memory_summary"],
        )

        return {
            "response_text": text,
            "response_buttons": _CONFUSED_PATIENT_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "fallback_count": fallback_count},
        }

    return node
