from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies.admin import (
    get_committing_error_query_service,
    get_conversation_query_service,
    get_error_query_service,
    get_graph_state_query_service,
    get_kpi_name_catalog,
    get_kpi_query_service,
    get_reset_conversation_use_case,
    get_run_query_service,
)
from app.api.dependencies.auth import require_csrf, require_role
from app.api.dependencies.gateways import get_agreement_gateway, get_ycloud_client
from app.application.admin.conversation_queries import ConversationQueryService
from app.application.admin.error_queries import ErrorQueryService
from app.application.admin.graph_state_queries import GraphState, GraphStateQueryService
from app.application.admin.graph_topology import GraphView, get_graph_topology
from app.application.admin.kpi_names import KpiNameCatalog
from app.application.admin.kpi_queries import (
    DailyCount,
    KpiEvidence,
    KpiPeriod,
    KpiQueryService,
    Kpis,
    TopEntry,
)
from app.application.admin.run_queries import RunQueryService
from app.application.agreements.list_agreements import ListAgreementsUseCase
from app.application.conversations.reset_conversation import ResetConversationUseCase
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_TECHNICAL, ROLES
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.error_record import ErrorRecord
from app.domain.repositories.gateways import AgreementGateway
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.auth.session_tokens import SessionPayload
from app.infrastructure.ycloud.client import YCloudClient
from app.infrastructure.ycloud.exceptions import YCloudAPIError
from app.infrastructure.ycloud.flows import (
    PATIENT_INTAKE_FLOW_SCREEN_ID,
    build_patient_intake_flow_json,
    build_registration_flow_json,
    build_verification_flow_json,
    load_flow_header_image_base64,
)

#: `/admin/api` (not bare `/admin`) — the PRD.md §44 routes
#: (`/admin/conversations`, `/admin/errors`, `/admin/runs/{id}`) name
#: HTML pages a human visits in a browser, not this JSON data layer. The
#: panel's own static pages (`app/static/admin/`) occupy those exact
#: paths and fetch their data from here client-side.
router = APIRouter(prefix="/admin/api", tags=["admin"])

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
    input_summary: str
    output_summary: str


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


class MeResponse(BaseModel):
    username: str
    role: str


@router.get("/me", response_model=MeResponse)
async def get_me(
    session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
) -> MeResponse:
    """The panel's own pages call this on load — both to confirm the
    session cookie is still valid (a 401 here is the page's cue to
    redirect to `/admin/login`) and to learn the caller's `role`, which
    the signed session cookie carries but no client-side JS can read
    directly (it's `HttpOnly`, and `/admin/login`'s own response body is
    only ever seen once, at login time — a page opened fresh in a new tab
    has no other way to know it).
    """
    return MeResponse(username=session.username, role=session.role)


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


class GraphNodeResponse(BaseModel):
    id: str
    label: str
    kind: Literal["start", "end", "node"]
    traced: bool


class GraphEdgeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(serialization_alias="from")
    to: str
    conditional: bool


class AgentGraphResponse(BaseModel):
    id: Literal["main", "appointment_decision", "first_visit_intake"]
    label: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]

    @classmethod
    def from_view(cls, view: GraphView) -> "AgentGraphResponse":
        return cls(
            id=view.id,  # type: ignore[arg-type]
            label=view.label,
            nodes=[
                GraphNodeResponse(id=n.id, label=n.label, kind=n.kind, traced=n.traced)
                for n in view.nodes
            ],
            edges=[
                GraphEdgeResponse(from_=e.source, to=e.target, conditional=e.conditional)
                for e in view.edges
            ],
        )


class AgentGraphsResponse(BaseModel):
    graphs: list[AgentGraphResponse]


@router.get("/graphs", response_model=AgentGraphsResponse, response_model_by_alias=True)
async def get_agent_graphs(
    response: Response,
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
) -> AgentGraphsResponse:
    """Static agent topology (read from the compiled graphs). `private` because the
    route sits behind admin auth: a shared cache must not store it."""
    response.headers["Cache-Control"] = "private, max-age=300"
    return AgentGraphsResponse(
        graphs=[AgentGraphResponse.from_view(g) for g in get_graph_topology()]
    )


class NodeStateResponse(BaseModel):
    count: int
    failed: int
    running: int
    last_status: str
    last_at: datetime
    avg_ms: float | None
    p50_ms: float | None
    last_error_id: str | None
    last_run_id: str


class GraphStateResponse(BaseModel):
    generated_at: datetime
    window: str
    nodes: dict[str, NodeStateResponse]
    unmapped: list[str]
    truncated: bool

    @classmethod
    def from_state(cls, state: GraphState) -> "GraphStateResponse":
        return cls(
            generated_at=state.generated_at,
            window=state.window,
            nodes={
                name: NodeStateResponse(
                    count=node.count,
                    failed=node.failed,
                    running=node.running,
                    last_status=node.last_status,
                    last_at=node.last_at,
                    avg_ms=node.avg_ms,
                    p50_ms=node.p50_ms,
                    last_error_id=node.last_error_id,
                    last_run_id=node.last_run_id,
                )
                for name, node in state.nodes.items()
            },
            unmapped=list(state.unmapped),
            truncated=state.truncated,
        )


@router.get("/graphs/state", response_model=GraphStateResponse)
async def get_graph_state(
    response: Response,
    window: Literal["15m", "1h", "24h"] = "1h",
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: GraphStateQueryService = Depends(get_graph_state_query_service),
) -> GraphStateResponse:
    """Live per-node aggregates over the window. `no-store`: it is polled and must
    never be served stale."""
    response.headers["Cache-Control"] = "no-store"
    state = await query_service.get_state(window, datetime.now(UTC))
    return GraphStateResponse.from_state(state)


class KpiPeriodResponse(BaseModel):
    date_from: date
    date_to: date
    days: int
    start: datetime
    end: datetime

    @classmethod
    def from_period(cls, period: KpiPeriod) -> "KpiPeriodResponse":
        return cls(
            date_from=period.date_from,
            date_to=period.date_to,
            days=period.days,
            start=period.start,
            end=period.end,
        )


class KpiTotalResponse(BaseModel):
    current: int
    previous: int
    #: Percentage change vs the previous period; null when `previous` is 0.
    change_pct: float | None

    @classmethod
    def of(cls, current: int, previous: int) -> "KpiTotalResponse":
        change = round((current - previous) / previous * 100, 1) if previous else None
        return cls(current=current, previous=previous, change_pct=change)


class KpiTotalsResponse(BaseModel):
    taken: KpiTotalResponse
    cancelled: KpiTotalResponse  # via bot only
    rescheduled: KpiTotalResponse


class KpiDailyResponse(BaseModel):
    date: date
    taken: int
    cancelled: int

    @classmethod
    def from_daily(cls, daily: DailyCount) -> "KpiDailyResponse":
        return cls(date=daily.date, taken=daily.taken, cancelled=daily.cancelled)


class KpiTopEntryResponse(BaseModel):
    id: str
    label: str
    count: int

    @classmethod
    def from_entry(cls, entry: TopEntry) -> "KpiTopEntryResponse":
        return cls(id=entry.id, label=entry.label, count=entry.count)


class KpiEvidenceResponse(BaseModel):
    taken_with: int
    taken_without: int
    cancelled_with: int
    cancelled_without: int
    truncated: bool

    @classmethod
    def from_evidence(cls, evidence: KpiEvidence) -> "KpiEvidenceResponse":
        return cls(
            taken_with=evidence.taken_with,
            taken_without=evidence.taken_without,
            cancelled_with=evidence.cancelled_with,
            cancelled_without=evidence.cancelled_without,
            truncated=evidence.truncated,
        )


class KpisResponse(BaseModel):
    """Aggregates only: counts and ids/labels of professionals and specialties, never
    patient data."""

    generated_at: datetime
    period: KpiPeriodResponse
    previous_period: KpiPeriodResponse
    totals: KpiTotalsResponse
    per_day: list[KpiDailyResponse]
    top_professionals: list[KpiTopEntryResponse]
    top_specialties: list[KpiTopEntryResponse]
    weekday: list[int]  # 7 entries, 0 = Monday
    hour: list[int]  # 24 entries, clinic hour of day
    without_slot: int
    evidence: KpiEvidenceResponse
    truncated: bool
    previous_truncated: bool

    @classmethod
    def from_kpis(cls, kpis: Kpis) -> "KpisResponse":
        return cls(
            generated_at=kpis.generated_at,
            period=KpiPeriodResponse.from_period(kpis.period),
            previous_period=KpiPeriodResponse.from_period(kpis.previous_period),
            totals=KpiTotalsResponse(
                taken=KpiTotalResponse.of(kpis.taken, kpis.previous.taken),
                cancelled=KpiTotalResponse.of(kpis.cancelled, kpis.previous.cancelled),
                rescheduled=KpiTotalResponse.of(kpis.rescheduled, kpis.previous.rescheduled),
            ),
            per_day=[KpiDailyResponse.from_daily(d) for d in kpis.per_day],
            top_professionals=[KpiTopEntryResponse.from_entry(e) for e in kpis.top_professionals],
            top_specialties=[KpiTopEntryResponse.from_entry(e) for e in kpis.top_specialties],
            weekday=list(kpis.weekday),
            hour=list(kpis.hour),
            without_slot=kpis.without_slot,
            evidence=KpiEvidenceResponse.from_evidence(kpis.evidence),
            truncated=kpis.truncated,
            previous_truncated=kpis.previous_truncated,
        )


_KPI_DEFAULT_DAYS = 30
_KPI_RANGE_ERROR = (
    "Rango de fechas inválido: 'from' no puede ser posterior a 'to' "
    "ni el período superar los 366 días."
)


@router.get("/kpis", response_model=KpisResponse)
async def get_kpis(
    response: Response,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    _session: SessionPayload = Depends(require_role(*_ANY_AUTHENTICATED_ROLE)),
    query_service: KpiQueryService = Depends(get_kpi_query_service),
    name_catalog: KpiNameCatalog = Depends(get_kpi_name_catalog),
    settings: Settings = Depends(get_settings),
) -> KpisResponse:
    """Appointment KPIs for a clinic-local date range (default: the last 30 days up to
    today). Labels come from a best-effort Dentalink catalog; on any failure the ids are
    used as labels. `no-store`: figures must never be served stale."""
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(UTC)
    date_to = to if to is not None else now.astimezone(ZoneInfo(settings.clinic_timezone)).date()
    date_from = from_ if from_ is not None else date_to - timedelta(days=_KPI_DEFAULT_DAYS - 1)
    names = await name_catalog.load()
    try:
        kpis = await query_service.get_kpis(
            date_from,
            date_to,
            now,
            professional_names=names.professionals.get,
            specialty_names=names.specialties.get,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=_KPI_RANGE_ERROR) from error
    return KpisResponse.from_kpis(kpis)


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


class FlowCreationResponse(BaseModel):
    patient_intake_flow_id: str
    verification_flow_id: str
    registration_flow_id: str


@router.post("/flows/create", response_model=FlowCreationResponse)
async def create_patient_flows(
    _role: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    ycloud_client: YCloudClient = Depends(get_ycloud_client),
    agreement_gateway: AgreementGateway = Depends(get_agreement_gateway),
) -> FlowCreationResponse:
    """One-time setup action (no PRD.md section — this session's own
    brief): creates and publishes the patient-identification WhatsApp
    Flows against the real YCloud/Meta account: the single intake Flow
    (patients and new patients) plus the legacy verification/registration
    pair it replaces.

    Run this ONCE per environment, then copy the returned ids into
    `YCLOUD_PATIENT_INTAKE_FLOW_ID` (or, for the legacy pair,
    `YCLOUD_VERIFICATION_FLOW_ID`/`YCLOUD_REGISTRATION_FLOW_ID`) — nothing
    persists this response, and re-running creates duplicate Flows rather
    than updating the existing ones (Meta has no update-in-place for an
    already-published Flow; editing forks a new draft instead).
    `ADMIN_TECHNICAL`-only and CSRF-checked, same posture as this panel's
    other mutating routes.
    """
    # Intake first: if Meta rejects its JSON, no duplicate legacy Flows exist yet.
    patient_intake_flow_id = await ycloud_client.create_flow(
        name="Datos de paciente",
        categories=["SIGN_UP"],
        flow_json=await _intake_flow_json(agreement_gateway),
        publish=True,
    )
    verification_flow_id = await ycloud_client.create_flow(
        name="Verificación de paciente",
        categories=["SIGN_UP"],
        flow_json=build_verification_flow_json(),
        publish=True,
    )
    registration_flow_id = await ycloud_client.create_flow(
        name="Registro de paciente",
        categories=["SIGN_UP"],
        flow_json=build_registration_flow_json(),
        publish=True,
    )
    return FlowCreationResponse(
        patient_intake_flow_id=patient_intake_flow_id,
        verification_flow_id=verification_flow_id,
        registration_flow_id=registration_flow_id,
    )


async def _intake_flow_json(agreement_gateway: AgreementGateway) -> str:
    """The intake Flow with the clinic's live convenios in its dropdown and the
    logo as header. A Dentalink failure propagates: shipping a Flow whose
    dropdown silently lacks every convenio would be worse than no Flow."""
    agreements = await ListAgreementsUseCase(agreement_gateway).execute()
    return build_patient_intake_flow_json(
        header_image_base64=load_flow_header_image_base64(),
        agreement_names=[agreement.name for agreement in agreements],
    )


class IntakeDraftResponse(BaseModel):
    flow_id: str
    preview_url: str


@router.post("/flows/intake-draft", response_model=IntakeDraftResponse)
async def create_intake_flow_draft(
    _role: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    ycloud_client: YCloudClient = Depends(get_ycloud_client),
    agreement_gateway: AgreementGateway = Depends(get_agreement_gateway),
) -> IntakeDraftResponse:
    """Creates ONLY the intake Flow as an unpublished draft (live convenios in
    the dropdown, clinic logo as header) and returns its preview URL, so the
    clinic can review it before anything is published or sent. Same posture
    as `/flows/create`: `ADMIN_TECHNICAL`-only and CSRF-checked.
    """
    # Meta requires a Flow name that is unique within the WhatsApp Business account, so
    # every draft carries a timestamp instead of colliding with an earlier Flow.
    name = f"Datos de paciente {datetime.now(UTC):%Y%m%d-%H%M%S}"
    try:
        flow_id = await ycloud_client.create_flow(
            name=name,
            categories=["SIGN_UP"],
            flow_json=await _intake_flow_json(agreement_gateway),
            publish=False,
        )
        preview_url = await ycloud_client.get_flow_preview_url(flow_id)
    except YCloudAPIError as error:
        # Surface Meta's own message (technical admins only) instead of a bare 500.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return IntakeDraftResponse(flow_id=flow_id, preview_url=preview_url)


class IntakeDraftSendRequest(BaseModel):
    flow_id: str
    to: str

    @field_validator("to")
    @classmethod
    def _to_must_be_e164(cls, value: str) -> str:
        return str(PhoneNumber(value))


class IntakeDraftSendResponse(BaseModel):
    message_id: str


@router.post("/flows/intake-draft/send", response_model=IntakeDraftSendResponse)
async def send_intake_flow_draft(
    body: IntakeDraftSendRequest,
    _role: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    ycloud_client: YCloudClient = Depends(get_ycloud_client),
) -> IntakeDraftSendResponse:
    """Sends the intake Flow to one phone so it can be reviewed on a real device.

    The Flow must be PUBLISHED: YCloud's Flow message schema has no draft mode, so Meta
    rejects a draft with `[131009] flow_id is invalid`. The phone must have written to
    the clinic number within the last 24 hours. Same posture as the other Flow routes.
    Do not press "Enviar" in the test form: the reply reaches the agent like a real
    patient's.
    """
    try:
        message_id = await ycloud_client.send_flow(
            body.to,
            "Probando el formulario de datos del paciente (borrador).",
            flow_id=body.flow_id,
            flow_screen_id=PATIENT_INTAKE_FLOW_SCREEN_ID,
            flow_cta="Ver formulario",
            flow_token=f"draft-test:{body.flow_id}",
        )
    except YCloudAPIError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return IntakeDraftSendResponse(message_id=message_id)
