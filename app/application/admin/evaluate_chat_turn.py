from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.domain.entities.agent_run import AgentRun
from app.domain.entities.contact import Contact
from app.domain.entities.conversation import Conversation
from app.domain.entities.message import Message
from app.domain.entities.node_execution import NodeExecution
from app.domain.entities.tool_execution import ToolExecution
from app.domain.repositories.agent_invoker import AgentInvoker
from app.domain.repositories.agent_run_repository import AgentRunRepository
from app.domain.repositories.contact_repository import ContactRepository
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.gateways import MessagingGateway
from app.domain.repositories.message_repository import MessageRepository
from app.domain.repositories.node_execution_repository import NodeExecutionRepository
from app.domain.repositories.tool_execution_repository import ToolExecutionRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.external_message_id import ExternalMessageId
from app.domain.value_objects.phone_number import PhoneNumber

#: Fixed synthetic contact backing every `/internal/eval/chat` turn (PRD.md
#: §61: "las evaluaciones nunca deberán utilizar datos reales de pacientes")
#: — never a real patient/phone, and shared across eval calls only within
#: the single isolated, all-fake `AgentInvoker` this use case is always
#: constructed with (see `app.api.dependencies.internal_eval`), never the
#: production one.
EVAL_CONTACT_ID = "eval-contact"
EVAL_PHONE = PhoneNumber("+5490000000000")


@dataclass
class ChatTurnResult:
    """One evaluated turn's observable outcome — what Promptfoo's custom
    assertions (PRD.md §58's `assertions/custom.js`) inspect to check
    things like "did NOT call cancel_appointment before confirmation"
    (PRD.md §61's own example).
    """

    reply_text: str | None
    agent_run: AgentRun | None
    node_executions: list[NodeExecution]
    tool_executions: list[ToolExecution]


class EvaluateChatTurnUseCase:
    """Backs `POST /internal/eval/chat` (PRD.md §61).

    Recreates just enough of `IngestMessageUseCase`'s persistence step
    (get-or-create contact/conversation, save the inbound message) to hand
    a real message off to `AgentInvoker.handle()` — deliberately skipping
    the debounce window (PRD.md §61's diagram has no debounce box: an eval
    turn must run deterministically and immediately, not wait out a
    real-time window).
    """

    def __init__(
        self,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        messages: MessageRepository,
        agent_runs: AgentRunRepository,
        node_executions: NodeExecutionRepository,
        tool_executions: ToolExecutionRepository,
        agent_invoker: AgentInvoker,
        messaging_gateway: MessagingGateway,
    ) -> None:
        self._conversations = conversations
        self._contacts = contacts
        self._messages = messages
        self._agent_runs = agent_runs
        self._node_executions = node_executions
        self._tool_executions = tool_executions
        self._agent_invoker = agent_invoker
        self._messaging_gateway = messaging_gateway

    async def execute(
        self, conversation_id: ConversationId, message: str, now: datetime
    ) -> ChatTurnResult:
        await self._ensure_eval_contact()
        await self._ensure_conversation(conversation_id, now)

        inbound = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            external_message_id=ExternalMessageId(str(uuid4())),
            direction="inbound",
            text=message,
            created_at=now,
        )
        await self._messages.save(inbound)

        await self._agent_invoker.handle(conversation_id, [inbound.id], message, None)

        agent_run = await self._agent_runs.get_latest_by_conversation_id(conversation_id)
        node_executions: list[NodeExecution] = []
        tool_executions: list[ToolExecution] = []
        if agent_run is not None:
            node_executions = await self._node_executions.get_by_agent_run_id(agent_run.id)
            tool_executions = await self._tool_executions.get_by_agent_run_id(agent_run.id)

        # `sent_messages` reflects only this call's traffic — the invoker
        # (and its `MessagingGateway`) are freshly built per eval request,
        # never shared across calls (see `app.api.dependencies.internal_eval`).
        sent = getattr(self._messaging_gateway, "sent_messages", [])
        reply_text = sent[-1][1] if sent else None

        return ChatTurnResult(
            reply_text=reply_text,
            agent_run=agent_run,
            node_executions=node_executions,
            tool_executions=tool_executions,
        )

    async def _ensure_eval_contact(self) -> None:
        if await self._contacts.get_by_id(EVAL_CONTACT_ID) is None:
            await self._contacts.save(
                Contact(id=EVAL_CONTACT_ID, phone=EVAL_PHONE, patient_id=None)
            )

    async def _ensure_conversation(self, conversation_id: ConversationId, now: datetime) -> None:
        if await self._conversations.get_by_id(conversation_id) is None:
            await self._conversations.save(
                Conversation(
                    id=conversation_id, contact_id=EVAL_CONTACT_ID, mode="agent", created_at=now
                )
            )
