from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies.admin import (
    get_committing_error_query_service,
    get_conversation_query_service,
    get_error_query_service,
    get_reset_conversation_use_case,
    get_run_query_service,
)
from app.api.dependencies.auth import require_csrf, require_role
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.run_queries import RunQueryService
from app.application.conversations.reset_conversation import ResetConversationUseCase
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_TECHNICAL, ROLES
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.error_record import ErrorRecord
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/admin", tags=["admin"])

#: PRD.md §74.3: "respuestas genéricas... protección contra enumeración de
#: identificadores" — every missing-resource path in this module returns
#: this exact message, whether the id is malformed, unknown, or (for an
#: authenticated-but-unauthorized caller) simply forbidden to view.
_NOT_FOUND_DETAIL = "Not found."

_ANY_AUTHENTICATED_ROLE = tuple(ROLES)


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    patient_or_identifier: str
    mode: str
    last_message_text: str | None
    last_message_at: datetime | None
    latest_run_status: str | None
    error_count: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    direction: str
    text: str
    created_at: datetime
    message_type: str
    media_status: str | None
    transcription_status: str | None


class NodeExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_name: str
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    error_id: str | None


class ToolExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_execution_id: str | None
    tool_name: str
    provider: str
    operation: str
    status: str
    http_status: str | None
    duration_ms: int
    error_id: str | None
    created_at: datetime


class AgentRunResponse(BaseModel):
    id: str
    conversation_id: str
    message_id: str
    trace_id: str
    prompt_version: str
    model: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    current_node: str | None
    error_id: str | None

    @classmethod
    def from_entity(cls, run: AgentRun) -> "AgentRunResponse":
        return cls(
            id=run.id,
            conversation_id=str(run.conversation_id),
            message_id=run.message_id,
            trace_id=run.trace_id,
            prompt_version=run.prompt_version,
            model=run.model,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            current_node=run.current_node,
            error_id=run.error_id,
        )


class ErrorResponse(BaseModel):
    id: str
    trace_id: str | None
    conversation_id: str | None
    agent_run_id: str | None
    source: str
    error_type: str
    error_code: str | None
    message: str
    technical_detail: str | None
    severity: str
    retryable: bool
    created_at: datetime
    resolved_at: datetime | None

    @classmethod
    def from_entity(cls, error: ErrorRecord) -> "ErrorResponse":
        return cls(
            id=error.id,
            trace_id=error.trace_id,
            conversation_id=str(error.conversation_id) if error.conversation_id else None,
            agent_run_id=error.agent_run_id,
            source=error.source,
            error_type=error.error_type,
            error_code=error.error_code,
            message=error.message,
            technical_detail=error.technical_detail,
            severity=error.severity,
            retryable=error.retryable,
            created_at=error.created_at,
            resolved_at=error.resolved_at,
        )


class ConversationResponse(BaseModel):
    id: str
    contact_id: str
    mode: str
    input_state: str
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]
    agent_runs: list[AgentRunResponse]
    errors: list[ErrorResponse]


class RunDetailResponse(BaseModel):
    agent_run: AgentRunResponse
    node_executions: list[NodeExecutionResponse]
    tool_executions: list[ToolExecutionResponse]


class ConfigResponse(BaseModel):
    """PRD.md §75.3's "ADMIN_CLINIC no accede a configuración técnica
    restringida" needs SOME technical-config resource to test against —
    PRD.md §44's own three routes are all clinical-data views, none of them
    that. This route is this change's minimal addition to make that rule
    testable: booleans only, never a secret's actual value.
    """

    internal_eval_enabled: bool
    groq_configured: bool
    ycloud_configured: bool
    dentalink_configured: bool


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: ConversationQueryService = Depends(get_conversation_query_service),
) -> list[ConversationSummaryResponse]:
    summaries = await query_service.list_conversations()
    return [ConversationSummaryResponse.model_validate(s) for s in summaries]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
    conversation_id: str,
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: ConversationQueryService = Depends(get_conversation_query_service),
) -> ConversationDetailResponse:
    detail = await query_service.get_conversation_detail(ConversationId(conversation_id))
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    return ConversationDetailResponse(
        conversation=ConversationResponse(
            id=str(detail.conversation.id),
            contact_id=detail.conversation.contact_id,
            mode=detail.conversation.mode,
            input_state=detail.conversation.input_state,
            created_at=detail.conversation.created_at,
        ),
        messages=[MessageResponse.model_validate(m) for m in detail.messages],
        agent_runs=[AgentRunResponse.from_entity(r) for r in detail.agent_runs],
        errors=[ErrorResponse.from_entity(e) for e in detail.errors],
    )


@router.post("/conversations/{conversation_id}/reset", response_model=ConversationDetailResponse)
async def reset_conversation(
    conversation_id: str,
    _role: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    reset_use_case: ResetConversationUseCase = Depends(get_reset_conversation_use_case),
    query_service: ConversationQueryService = Depends(get_conversation_query_service),
) -> ConversationDetailResponse:
    """`ADMIN_TECHNICAL`-only and CSRF-checked, same posture as
    `resolve_error` below — this route is irreversibly destructive
    (`ResetConversationUseCase`'s own docstring), so it needs the same
    protection as this panel's other mutating route.

    NEVER call this against a real patient conversation — wipes the
    conversation's messages, compacted contact memory, LangGraph checkpoint
    thread, and `mode`/`input_state` back to defaults, so a real WhatsApp
    number can be re-tested from a clean slate during development.
    """
    reset = await reset_use_case.execute(ConversationId(conversation_id))
    if reset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    detail = await query_service.get_conversation_detail(ConversationId(conversation_id))
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    return ConversationDetailResponse(
        conversation=ConversationResponse(
            id=str(detail.conversation.id),
            contact_id=detail.conversation.contact_id,
            mode=detail.conversation.mode,
            input_state=detail.conversation.input_state,
            created_at=detail.conversation.created_at,
        ),
        messages=[MessageResponse.model_validate(m) for m in detail.messages],
        agent_runs=[AgentRunResponse.from_entity(r) for r in detail.agent_runs],
        errors=[ErrorResponse.from_entity(e) for e in detail.errors],
    )


@router.get("/errors", response_model=list[ErrorResponse])
async def list_errors(
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: ErrorQueryService = Depends(get_error_query_service),
) -> list[ErrorResponse]:
    errors = await query_service.list_errors()
    return [ErrorResponse.from_entity(e) for e in errors]


@router.get("/errors/{error_id}", response_model=ErrorResponse)
async def get_error_detail(
    error_id: str,
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: ErrorQueryService = Depends(get_error_query_service),
) -> ErrorResponse:
    error = await query_service.get_error_detail(error_id)
    if error is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return ErrorResponse.from_entity(error)


@router.post("/errors/{error_id}/resolve", response_model=ErrorResponse)
async def resolve_error(
    error_id: str,
    _role: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    query_service: ErrorQueryService = Depends(get_committing_error_query_service),
) -> ErrorResponse:
    """`ADMIN_TECHNICAL`-only and CSRF-checked — the panel's one mutating
    route (PRD.md §75.3 requires testing both a non-`ADMIN_TECHNICAL` role
    being rejected here and CSRF blocking an unauthorized request).
    """
    resolved = await query_service.resolve(error_id, now=datetime.now(UTC))
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return ErrorResponse.from_entity(resolved)


@router.get("/runs/{agent_run_id}", response_model=RunDetailResponse)
async def get_run_detail(
    agent_run_id: str,
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: RunQueryService = Depends(get_run_query_service),
) -> RunDetailResponse:
    detail = await query_service.get_run_detail(agent_run_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    return RunDetailResponse(
        agent_run=AgentRunResponse.from_entity(detail.agent_run),
        node_executions=[NodeExecutionResponse.model_validate(n) for n in detail.node_executions],
        tool_executions=[ToolExecutionResponse.model_validate(t) for t in detail.tool_executions],
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    _session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    return ConfigResponse(
        internal_eval_enabled=settings.internal_eval_enabled,
        groq_configured=bool(settings.groq_api_key),
        ycloud_configured=bool(settings.ycloud_api_key),
        dentalink_configured=bool(settings.dentalink_access_token),
    )
