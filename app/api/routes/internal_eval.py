from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies.auth import require_role
from app.api.dependencies.internal_eval import (
    get_evaluate_chat_turn_use_case,
    require_internal_eval_enabled,
)
from app.application.admin.evaluate_chat_turn import EvaluateChatTurnUseCase
from app.domain.entities.admin_user import ROLES
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/internal/eval", tags=["internal-eval"])

_ANY_AUTHENTICATED_ROLE = tuple(ROLES)


class EvalChatRequest(BaseModel):
    conversation_id: str
    message: str


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


@router.post("/chat", response_model=EvalChatResponse)
async def eval_chat(
    body: EvalChatRequest,
    _enabled: None = Depends(require_internal_eval_enabled),
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    use_case: EvaluateChatTurnUseCase = Depends(get_evaluate_chat_turn_use_case),
) -> EvalChatResponse:
    """PRD.md §61's isolated agent-behavior evaluation endpoint. Runs the
    real LangGraph agent against an entirely fake Dentalink/YCloud/LLM
    stack (see `app.api.dependencies.internal_eval`'s own docstring) — never
    real patient data, never a real external call.
    """
    result = await use_case.execute(
        ConversationId(body.conversation_id), body.message, now=datetime.now(UTC)
    )
    return EvalChatResponse(
        reply_text=result.reply_text,
        agent_run_id=result.agent_run.id if result.agent_run else None,
        agent_run_status=result.agent_run.status if result.agent_run else None,
        node_names=[n.node_name for n in result.node_executions],
        tool_names=[t.tool_name for t in result.tool_executions],
    )
