from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
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
EVAL_CONTACT_ID_PREFIX = "eval-contact-"
EVAL_PHONE = PhoneNumber("+5490000000000")


@dataclass(frozen=True)
class EvalOption:
    """One tappable option of an interactive reply: a reply button or a list row."""

    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class EvalFlow:
    """Marker for a WhatsApp Flow reply."""

    flow_id: str
    screen_id: str
    cta: str


ReplyKind = Literal["text", "buttons", "list", "flow", "location"]

#: Reply kind -> the fake gateway's own collection. One table for reading AND clearing,
#: so a new kind can never be read without also being cleared.
_COLLECTION_BY_KIND: dict[ReplyKind, str] = {
    "text": "sent_messages",
    "buttons": "sent_buttons",
    "list": "sent_lists",
    "flow": "sent_flows",
    "location": "sent_locations",
}


def eval_contact_id(conversation_id: ConversationId) -> str:
    """One synthetic contact per eval conversation: contact-scoped state (the
    compacted memory summary and its Redis cache key) never leaks between
    scenarios or runs.
    """
    return f"{EVAL_CONTACT_ID_PREFIX}{conversation_id}"


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
    #: What the patient saw: plain text or one of the interactive kinds.
    reply_kind: ReplyKind | None = None
    buttons: list[EvalOption] = field(default_factory=list)
    list_rows: list[EvalOption] = field(default_factory=list)
    flow: EvalFlow | None = None


@dataclass
class _Reply:
    text: str | None = None
    kind: ReplyKind | None = None
    buttons: list[EvalOption] = field(default_factory=list)
    list_rows: list[EvalOption] = field(default_factory=list)
    flow: EvalFlow | None = None


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
        self,
        conversation_id: ConversationId,
        message: str,
        now: datetime,
        button_payload: str | None = None,
    ) -> ChatTurnResult:
        await self._ensure_eval_contact(conversation_id)
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

        try:
            await self._agent_invoker.handle(conversation_id, [inbound.id], message, button_payload)
            reply = self._read_reply()
        finally:
            # Runs on every path, also when the agent raised: the gateway outlives a
            # turn, so a leftover reply would be reported as the next turn's.
            self._consume_captured_replies()

        agent_run = await self._agent_runs.get_latest_by_conversation_id(conversation_id)
        node_executions: list[NodeExecution] = []
        tool_executions: list[ToolExecution] = []
        if agent_run is not None:
            node_executions = await self._node_executions.get_by_agent_run_id(agent_run.id)
            tool_executions = await self._tool_executions.get_by_agent_run_id(agent_run.id)

        return ChatTurnResult(
            reply_text=reply.text,
            agent_run=agent_run,
            node_executions=node_executions,
            tool_executions=tool_executions,
            reply_kind=reply.kind,
            buttons=reply.buttons,
            list_rows=reply.list_rows,
            flow=reply.flow,
        )

    def _captured(self, kind: ReplyKind) -> list[Any]:
        collection = getattr(self._messaging_gateway, _COLLECTION_BY_KIND[kind], None)
        return collection if isinstance(collection, list) else []

    def _consume_captured_replies(self) -> None:
        for kind in _COLLECTION_BY_KIND:
            self._captured(kind).clear()
        log = getattr(self._messaging_gateway, "sent_log", None)
        if isinstance(log, list):
            log.clear()

    def _last_sent(self) -> tuple[ReplyKind, Any] | None:
        """The last message actually sent, chronologically. Falls back to the newest
        entry of the first non-empty collection when the gateway keeps no send log.
        """
        log = getattr(self._messaging_gateway, "sent_log", None)
        if isinstance(log, list) and log:
            kind, index = log[-1]
            return kind, self._captured(kind)[index]
        for kind in _COLLECTION_BY_KIND:
            captured = self._captured(kind)
            if captured:
                return kind, captured[-1]
        return None

    def _read_reply(self) -> "_Reply":
        """The reply is the LAST message sent this turn; its options (buttons, list
        rows, flow) are exposed only when that message is the interactive one.
        """
        last = self._last_sent()
        if last is None:
            return _Reply()
        kind, entry = last
        reply = _Reply(kind=kind)
        if kind == "buttons":
            reply.text = entry[1]
            reply.buttons = [EvalOption(id=b.id, title=b.title) for b in entry[2]]
        elif kind == "list":
            reply.text = entry[1]
            reply.list_rows = [
                EvalOption(id=r.id, title=r.title, description=r.description) for r in entry[2].rows
            ]
        elif kind == "flow":
            reply.text = entry[1]
            reply.flow = EvalFlow(
                flow_id=entry[2].flow_id, screen_id=entry[2].flow_screen_id, cta=entry[2].flow_cta
            )
        elif kind == "text":
            reply.text = entry[1]
        return reply

    async def _ensure_eval_contact(self, conversation_id: ConversationId) -> None:
        contact_id = eval_contact_id(conversation_id)
        if await self._contacts.get_by_id(contact_id) is None:
            await self._contacts.save(Contact(id=contact_id, phone=EVAL_PHONE, patient_id=None))

    async def _ensure_conversation(self, conversation_id: ConversationId, now: datetime) -> None:
        if await self._conversations.get_by_id(conversation_id) is None:
            await self._conversations.save(
                Conversation(
                    id=conversation_id,
                    contact_id=eval_contact_id(conversation_id),
                    mode="agent",
                    created_at=now,
                )
            )
