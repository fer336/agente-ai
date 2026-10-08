import asyncio
import random
from collections.abc import Callable, Sequence

from app.agent.nodes.node_protocol import AgentNode
from app.agent.state import AgentState
from app.application.conversations.set_conversation_input_state import HUMAN as INPUT_STATE_HUMAN
from app.application.conversations.set_conversation_input_state import (
    SetConversationInputStateUseCase,
)
from app.application.conversations.set_conversation_mode import SetConversationModeUseCase
from app.application.handoff.request_human_handoff import RequestHumanHandoffUseCase
from app.application.messages.mirror_to_chatwoot import MirrorMessageToChatwootUseCase
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import HumanHandoffGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber

#: Patient-facing acknowledgements, picked at random so the reply is not always the
#: same. They all say the same things: an advisor will get in touch soon, in this very
#: chat, and the assistant pauses so the team can take over (the node really does put
#: the conversation in human mode). They never name the internal "administración"
#: destination (the node tests pin that) and never promise a concrete time.
HANDOFF_ACK_MESSAGES: tuple[str, ...] = (
    "¡Listo! 😊 Te paso con una persona del equipo de Smiling Pilar: "
    "en breve un asesor se va a comunicar con vos por este mismo chat. "
    "Yo me pauso para que ellos puedan seguir con la conversación.",
    "Perfecto, ya aviso al equipo de la clínica 💙 "
    "Un asesor se comunicará con vos en breve, en este mismo chat. "
    "Mientras tanto me pauso, así pueden continuar la conversación sin interrupciones.",
    "¡Gracias por avisarnos! 🙌 Te derivo con el equipo de la clínica: "
    "un asesor te va a escribir en breve por este mismo chat. "
    "Me pauso para que puedan seguir con la conversación.",
    "Dale, te conecto con el equipo de la clínica 🦷 "
    "En breve un asesor te contesta por este mismo chat. "
    "Yo me quedo en pausa para que ellos sigan la conversación.",
    "Entendido 😊 Ya le dejo tu consulta a una persona de la clínica. "
    "Un asesor se va a comunicar con vos en breve, en este mismo chat. "
    "Me pauso para que el equipo pueda seguir con vos.",
    "Con gusto 💙 Te comunico con el equipo de Smiling Pilar. "
    "En breve un asesor continuará la conversación con vos desde este mismo chat. "
    "Yo me pauso para no interrumpirlos.",
)


def create_handoff_node(
    handoff_gateway: HumanHandoffGateway,
    conversation_repository: ConversationRepository,
    mirror_to_chatwoot: MirrorMessageToChatwootUseCase | None = None,
    choose_message: Callable[[Sequence[str]], str] = random.choice,
) -> AgentNode:
    """Derives the conversation to administración (PRD.md §21-22).

    Covers both the manual "💬 Administración" selection and PRD.md §22's
    automatic-derivation phrases ("voy a llegar tarde", "necesito hablar con
    una persona", ...) — both reach this node the same way, via
    `resolve_interaction` classifying `intent="handoff"`. The automatic-
    phrase detection lives in the classifier (`FakeLLMProvider`'s handoff
    keywords for now); this node only executes the handoff mechanics
    uniformly once routed here, per PRD.md §22: "No se intentará modificar
    automáticamente un turno porque el paciente indique que llegará tarde.
    Ese caso siempre se deriva" — this node never inspects `appointment_action`
    or attempts any appointment operation, it only escalates.
    """
    request_handoff = RequestHumanHandoffUseCase(handoff_gateway)
    set_conversation_mode = SetConversationModeUseCase(conversation_repository)
    set_conversation_input_state = SetConversationInputStateUseCase(conversation_repository)

    async def node(state: AgentState) -> dict[str, object]:
        conversation_id = ConversationId(state["conversation_id"])
        await request_handoff.execute(conversation_id, reason=state["user_message"])
        await set_conversation_mode.execute(conversation_id, mode="human")
        await set_conversation_input_state.execute(conversation_id, INPUT_STATE_HUMAN)

        if mirror_to_chatwoot is not None:
            # Fire-and-forget, same "never delay the real reply" posture as
            # every other mirror call site — see
            # `MirrorMessageToChatwootUseCase`'s own docstring.
            phone = str(conversation_id).removeprefix("ycloud-")
            asyncio.create_task(
                mirror_to_chatwoot.escalate_to_administracion(
                    conversation_id, PhoneNumber(phone), phone
                )
            )

        return {
            "response_text": choose_message(HANDOFF_ACK_MESSAGES),
            "requires_handoff": True,
        }

    return node
