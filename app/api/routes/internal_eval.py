from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies.auth import require_role
from app.api.dependencies.internal_eval import (
    EvalUseCaseProvider,
    get_eval_use_case_provider,
    require_internal_eval_enabled,
)
from app.application.admin.evaluate_chat_turn import EvalFlow, EvalOption
from app.domain.entities.admin_user import ADMIN_TECHNICAL
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/internal/eval", tags=["internal-eval"])


class EvalChatRequest(BaseModel):
    conversation_id: str
    message: str
    #: Machine-readable id of a tapped reply button / list row (what the real
    #: webhook parses into `button_payload`); `message` then carries its title.
    button_payload: str | None = None


class EvalOptionOut(BaseModel):
    id: str
    title: str
    description: str | None = None


class EvalButtonOut(BaseModel):
    id: str
    title: str


class EvalFlowOut(BaseModel):
    flow_id: str
    screen_id: str
    cta: str


class EvalChatResponse(BaseModel):
    """PRD.md §61's own example checks exactly this shape of thing:
    `✓ identify_patient / ✓ get_appointments / ✓ request_confirmation /
    ✗ cancel_appointment antes de confirmación` — `node_names`/`tool_names`
    give Promptfoo's `assertions/custom.js` (PRD.md §58) what it needs to
    assert on call order/presence without re-deriving it from raw trace
    rows.
    """

    reply_text: str | None
    agent_run_id: str | None
    agent_run_status: str | None
    node_names: list[str]
    tool_names: list[str]
    #: "text" | "buttons" | "list" | "flow" | null (nothing sent).
    reply_kind: str | None = None
    buttons: list[EvalButtonOut] = []
    list_rows: list[EvalOptionOut] = []
    flow: EvalFlowOut | None = None


def _option_out(option: EvalOption) -> EvalOptionOut:
    return EvalOptionOut(id=option.id, title=option.title, description=option.description)


def _flow_out(flow: EvalFlow | None) -> EvalFlowOut | None:
    if flow is None:
        return None
    return EvalFlowOut(flow_id=flow.flow_id, screen_id=flow.screen_id, cta=flow.cta)


@router.post("/chat", response_model=EvalChatResponse)
async def eval_chat(
    body: EvalChatRequest,
    _enabled: None = Depends(require_internal_eval_enabled),
    _session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    use_case_for: EvalUseCaseProvider = Depends(get_eval_use_case_provider),
) -> EvalChatResponse:
    """`ADMIN_TECHNICAL`-only: with the endpoint permanently enabled, every
    other role gets 403. PRD.md §61's isolated agent-behavior evaluation endpoint. Runs the
    real LangGraph agent against a fake Dentalink/YCloud stack (see
    `app.api.dependencies.internal_eval`'s own docstring) — never real
    patient data or WhatsApp traffic. The LLM is fake unless
    `INTERNAL_EVAL_REAL_LLM` is on, which makes a real (billed) LLM call per
    turn and is meant to be enabled only for an audit window.
    """
    conversation_id = ConversationId(body.conversation_id)
    result = await use_case_for(conversation_id).execute(
        conversation_id,
        body.message,
        now=datetime.now(UTC),
        button_payload=body.button_payload or None,
    )
    return EvalChatResponse(
        reply_text=result.reply_text,
        agent_run_id=result.agent_run.id if result.agent_run else None,
        agent_run_status=result.agent_run.status if result.agent_run else None,
        node_names=[n.node_name for n in result.node_executions],
        tool_names=[t.tool_name for t in result.tool_executions],
        reply_kind=result.reply_kind,
        buttons=[EvalButtonOut(id=b.id, title=b.title) for b in result.buttons],
        list_rows=[_option_out(r) for r in result.list_rows],
        flow=_flow_out(result.flow),
    )
