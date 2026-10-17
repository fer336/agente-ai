from typing import cast

from app.agent.handoff_offer import (
    HANDOFF_OFFER_BUTTONS,
    HANDOFF_OFFER_FLAG_KEY,
    HANDOFF_OFFER_KEY,
    normalize_text,
)
from app.agent.nodes.llm_response import generate_or_fallback
from app.agent.nodes.location import asks_for_location, clinic_location_reply
from app.agent.nodes.node_protocol import AgentNode
from app.agent.nodes.payment_admin import PAYMENT_ADMIN_STATIC_MESSAGE
from app.agent.payment_questions import asks_about_payments
from app.agent.state import AgentState
from app.domain.entities.message import ROLE_USER
from app.domain.repositories.llm_provider import LLMProvider
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.menu_payloads import (
    MENU_ADMIN_PAYLOAD,
    MENU_MAIN_PAYLOAD,
    OPERATION_CREATE_PAYLOAD,
)
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT

#: Approved fixed reply for anything outside what the bot supports. Never LLM-generated:
#: the clinic signed off this exact wording.
OUT_OF_SCOPE_MESSAGE = (
    "Disculpame, con eso no te puedo ayudar por acá 🙏 Solo puedo guiarte con la "
    "información del menú principal.\n"
    "Si querés sacar un turno, tocá *Agendar una cita*. Y si necesitás otra cosa, "
    "escribile a *Administración* o volvé al *Menú*."
)
#: Static wording for a patient who typed instead of tapping the welcome
#: menu, used only when the LLM provider fails.
_CHOOSE_FROM_MENU_MESSAGE = (
    "Para poder continuar, elegí por favor una de las opciones del menú tocando el "
    "botón de abajo 👇"
)
#: Buttons of the out-of-scope reply: book (`OPERATION_CREATE_PAYLOAD`, the payload of the
#: welcome list's "📅 Agendar una cita" row), talk to a human, or back to the main menu.
#: `MENU_APPOINTMENT_PAYLOAD`/`MENU_SPECIALTIES_PAYLOAD` stay routable in
#: `resolve_interaction.py` for old chat history, this reply never sends them.
OUT_OF_SCOPE_BUTTONS = [
    InteractiveButton(id=OPERATION_CREATE_PAYLOAD, title="📅 Agendar una cita"),
    InteractiveButton(id=MENU_ADMIN_PAYLOAD, title="💬 Administración"),
    InteractiveButton(id=MENU_MAIN_PAYLOAD, title="📋 Menú principal"),
]


def _does_not_apologise_for_not_understanding(text: str) -> bool:
    """The patient just typed a greeting or a stray word: telling them "no te entendí" is
    the exact wording this reply exists to avoid, whatever the model was told."""
    return "entend" not in normalize_text(text)


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

    A turn outside what the bot supports gets the fixed `OUT_OF_SCOPE_MESSAGE` and the three
    static `OUT_OF_SCOPE_BUTTONS`, with no LLM call: the wording is clinic-approved and the
    fallback's whole job is to be a reliable safety net. The LLM is still used for the reminder
    right after the welcome menu (the patient typed instead of tapping). `fallback_count` keeps
    tracking consecutive unresolved turns.
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

        # The model's free-form answer (`pending_answer`, from `understand`) is never
        # delivered: only programmed capabilities answer. It is dropped here and, at most,
        # used as a signal that the patient is asking about payments.
        pending_answer = collected_data.get("pending_answer")
        collected_data = {
            k: v
            for k, v in collected_data.items()
            if k not in {"pending_answer", HANDOFF_OFFER_FLAG_KEY}
        }
        if asks_about_payments(state["user_message"]) or (
            isinstance(pending_answer, str) and asks_about_payments(pending_answer)
        ):
            # Payments and prices belong to Administración: fixed text, never improvised.
            return {
                "response_text": PAYMENT_ADMIN_STATIC_MESSAGE,
                "response_buttons": HANDOFF_OFFER_BUTTONS,
                "requires_handoff": False,
                "collected_data": {**collected_data, HANDOFF_OFFER_KEY: True},
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
                # Own intent: under "fallback" the model read the turn as "no te entendí"
                # and apologised despite the instruction.
                "welcome_menu_reminder",
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
                validator=_does_not_apologise_for_not_understanding,
            )
            return {
                "response_text": text,
                "response_buttons": None,
                "response_list": WELCOME_LIST,
                "requires_handoff": False,
                "collected_data": {**collected_data, "fallback_count": fallback_count},
            }

        return {
            "response_text": OUT_OF_SCOPE_MESSAGE,
            "response_buttons": OUT_OF_SCOPE_BUTTONS,
            "requires_handoff": False,
            "collected_data": {**collected_data, "fallback_count": fallback_count},
        }

    return node
