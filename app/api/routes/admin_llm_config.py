from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.admin import get_committing_admin_audit_log_repository
from app.api.dependencies.auth import require_csrf, require_role
from app.api.dependencies.config import get_runtime_config_service
from app.application.config.runtime_config_service import RuntimeConfigService
from app.domain.entities.admin_audit_log_entry import LLM_CONFIG_UPDATED, AdminAuditLogEntry
from app.domain.entities.admin_user import ADMIN_TECHNICAL
from app.domain.entities.runtime_agent_config import RUNTIME_AGENT_CONFIG_ID, RuntimeAgentConfig
from app.domain.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.infrastructure.auth.session_tokens import SessionPayload

#: `/admin/api` — same JSON-data-layer prefix as `app.api.routes.admin`
#: (see that module's own comment on why `/admin/api` and not bare
#: `/admin`). A separate router file, not an addition to the already
#: ~400-line `admin.py`, matching this codebase's one-router-file-per-
#: concern convention (`admin_auth.py`, `admin_docs.py`, `admin_pages.py`
#: are each their own file too).
router = APIRouter(prefix="/admin/api", tags=["admin-llm-config"])

_TEMPERATURE_RANGE = (0.0, 2.0)


class LlmConfigResponse(BaseModel):
    model: str
    temperature: float
    classify_intent_prompt: str
    extract_information_prompt: str
    generate_response_prompt: str
    updated_at: datetime
    updated_by: str

    @classmethod
    def from_entity(cls, config: RuntimeAgentConfig) -> "LlmConfigResponse":
        return cls(
            model=config.model,
            temperature=config.temperature,
            classify_intent_prompt=config.classify_intent_prompt,
            extract_information_prompt=config.extract_information_prompt,
            generate_response_prompt=config.generate_response_prompt,
            updated_at=config.updated_at,
            updated_by=config.updated_by,
        )


class LlmConfigUpdateRequest(BaseModel):
    model: str
    temperature: float
    classify_intent_prompt: str
    extract_information_prompt: str
    generate_response_prompt: str


def _validate_prompts(body: LlmConfigUpdateRequest) -> None:
    """Rejects a save that would silently break the agent's own prompt
    substitution.

    `OpenAICompatibleLLMProvider` fills these placeholders with plain
    `str.replace(...)`, not `.format()` — a missing placeholder never
    raises a `KeyError` downstream, it just silently never gets
    substituted (the model would never learn, e.g., which fields are
    still missing). That makes this the ONLY place that can catch the
    mistake, so it fails loudly here instead of degrading silently later.
    """
    if not body.model.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="El modelo no puede estar vacío.")
    low, high = _TEMPERATURE_RANGE
    if not low <= body.temperature <= high:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"La temperatura debe estar entre {low} y {high}.",
        )
    if not body.classify_intent_prompt.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="El prompt de clasificación no puede estar vacío."
        )
    if "{required_fields}" not in body.extract_information_prompt:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail='El prompt de extracción debe incluir el placeholder "{required_fields}".',
        )
    if "{intent}" not in body.generate_response_prompt:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail='El prompt de respuesta debe incluir el placeholder "{intent}".',
        )
    if "{collected_data}" not in body.generate_response_prompt:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail='El prompt de respuesta debe incluir el placeholder "{collected_data}".',
        )


@router.get("/llm-config", response_model=LlmConfigResponse)
async def get_llm_config(
    _session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    runtime_config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> LlmConfigResponse:
    """`ADMIN_TECHNICAL`-only even though it's a read — same posture as
    `GET /admin/api/config`: this is technical configuration, not
    clinical data, and PRD.md §75.3 requires `ADMIN_CLINIC` excluded from
    it. Never exposes an API key — none is stored here (see
    `RuntimeAgentConfig`'s own scope).
    """
    config = await runtime_config_service.get_config()
    return LlmConfigResponse.from_entity(config)


@router.put("/llm-config", response_model=LlmConfigResponse)
async def update_llm_config(
    body: LlmConfigUpdateRequest,
    session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL)),
    _csrf: SessionPayload = Depends(require_csrf),
    runtime_config_service: RuntimeConfigService = Depends(get_runtime_config_service),
    audit_log_repository: AdminAuditLogRepository = Depends(
        get_committing_admin_audit_log_repository
    ),
) -> LlmConfigResponse:
    """`ADMIN_TECHNICAL`-only and CSRF-checked, same posture as this
    panel's other mutating routes (`reset_conversation`, `resolve_error`).

    Preserves `debounce_seconds` from the existing config — it isn't part
    of this request's scope (model + prompts only), so a save here must
    never silently reset it to some default.
    """
    _validate_prompts(body)

    existing = await runtime_config_service.get_config()
    updated = RuntimeAgentConfig(
        id=RUNTIME_AGENT_CONFIG_ID,
        model=body.model,
        temperature=body.temperature,
        debounce_seconds=existing.debounce_seconds,
        classify_intent_prompt=body.classify_intent_prompt,
        extract_information_prompt=body.extract_information_prompt,
        generate_response_prompt=body.generate_response_prompt,
        updated_at=datetime.now(UTC),
        updated_by=session.username,
    )
    await runtime_config_service.save_config(updated)

    await audit_log_repository.save(
        AdminAuditLogEntry(
            id=str(uuid4()),
            admin_user_id=session.admin_user_id,
            username=session.username,
            action=LLM_CONFIG_UPDATED,
            resource_type="runtime_agent_config",
            resource_id=RUNTIME_AGENT_CONFIG_ID,
            success=True,
            created_at=updated.updated_at,
        )
    )

    return LlmConfigResponse.from_entity(updated)
