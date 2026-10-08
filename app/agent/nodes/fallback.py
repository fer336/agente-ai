from typing import cast

from app.agent.action_claims import guard_free_text_answer
from app.agent.handoff_offer import (
    HANDOFF_OFFER_BUTTONS,
    HANDOFF_OFFER_FLAG_KEY,
    HANDOFF_OFFER_KEY,
    answer_offers_handoff,
)
from app.agent.nodes.llm_response import (
    generate_or_fallback,
    without_mid_conversation_greeting,
)
from app.agent.nodes.location import asks_for_location, clinic_location_reply
from app.agent.nodes.node_protocol import AgentNode
from app.agent.nodes.payment_admin import PAYMENT_ADMIN_STATIC_MESSAGE
from app.agent.payment_questions import asks_about_payments
from app.agent.state import AgentState
from app.domain.entities.message import ROLE_USER
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, OPERATION_CREATE_PAYLOAD
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

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
#: Static wording for a patient who typed instead of tapping the welcome
#: menu, used only when the LLM provider fails.
_CHOOSE_FROM_MENU_MESSAGE = (
    "Para poder continuar, elegí por favor una de las opciones del menú tocando el "
    "botón de abajo 👇"
)
#: A first miss gets a plain "no te entendí"; only a repeat one
#: offers administración.
_ESCALATE_AFTER_ATTEMPTS = 2

_CONFUSED_PATIENT_BUTTONS = [
    InteractiveButton(id=OPERATION_CREATE_PAYLOAD, title="📅 Agendar una cita"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
]


def _welcome_menu_was_just_shown(recent_messages: list[dict[str, str]]) -> bool:
    """True when the last assistant message before the patient's current
    turn is the canonical welcome menu (no other bot reply since)."""
    for message in reversed(recent_messages):
        if message["role"] == ROLE_USER:
            continue
        return message["content"].startswith(WELCOME_TEXT)
    return False


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

        if asks_for_location(state["user_message"]):
            # Checked before `pending_answer`: the model's own free-text
            # "question" answer might describe an address from memory (or
            # nothing at all) instead of the clinic's real, verified
            # location — this always wins when the patient is asking to
            # get there, LLM answer or not. A native location card needs
            # no accompanying text (WhatsApp shows name/address on the
            # card itself), so this is the one reply with no LLM step.
            remaining = {k: v for k, v in collected_data.items() if k != "pending_answer"}
            return {**clinic_location_reply(), "collected_data": remaining}

        pending_answer = collected_data.get("pending_answer")
        if isinstance(pending_answer, str) and pending_answer.strip():
            # `resolve_interaction` already had the model answer a genuine
            # question, so there is nothing to be confused about — deliver
            # it, keep the menu as a way forward, and do NOT count this
            # turn as a failed one.
            flagged_offer = collected_data.get(HANDOFF_OFFER_FLAG_KEY)
            remaining = {
                k: v
                for k, v in collected_data.items()
                if k not in {"pending_answer", HANDOFF_OFFER_FLAG_KEY}
            }
            model_answer = without_mid_conversation_greeting(
                pending_answer, state["recent_messages"]
            )
            answer = guard_free_text_answer(model_answer)
            if answer != model_answer:
                # The guard swapped the answer for a safe one: the flag described the
                # discarded text, not this one.
                flagged_offer = None
            if asks_about_payments(answer):
                # Payments and prices belong to Administración: never improvised.
                answer = PAYMENT_ADMIN_STATIC_MESSAGE
                flagged_offer = True
            offers_handoff = answer_offers_handoff(answer, flagged=flagged_offer)
            if offers_handoff:
                remaining[HANDOFF_OFFER_KEY] = True
            return {
                "response_text": answer,
                "response_buttons": (
                    HANDOFF_OFFER_BUTTONS if offers_handoff else _CONFUSED_PATIENT_BUTTONS
                ),
                "requires_handoff": False,
                "collected_data": remaining,
            }

        fallback_count = cast(int, collected_data.get("fallback_count", 0)) + 1

        if _welcome_menu_was_just_shown(state["recent_messages"]):
            # The patient typed instead of tapping the welcome menu just
            # offered (typically a bare "Hola"): ask for a menu option
            # (no greeting — the welcome already greeted), re-attaching that
            # same menu so there is something to tap — not the 2-button
            # "no te entendí" safety net.
            text = await generate_or_fallback(
                llm_provider,
                state["conversation_id"],
                "fallback",
                {
                    "situacion": (
                        "Ya le mostramos el menú de bienvenida al paciente y, en lugar de "
                        "tocar una opción, escribió un mensaje."
                    ),
                    "instruccion": (
                        "Pedile con calidez que para poder continuar elija una de las "
                        "opciones del menú. No saludes, no digas que no lo entendiste, no "
                        "listes las opciones ni repitas sus nombres."
                    ),
                    "intentos_seguidos_sin_resolver": fallback_count,
                },
                _CHOOSE_FROM_MENU_MESSAGE,
                state["recent_messages"],
                state["contact_memory_summary"],
            )
            return {
                "response_text": text,
                "response_buttons": None,
                "response_list": WELCOME_LIST,
                "requires_handoff": False,
                "collected_data": {**collected_data, "fallback_count": fallback_count},
            }

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
