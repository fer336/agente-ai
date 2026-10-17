from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.admin import get_committing_admin_audit_log_repository
from app.api.dependencies.auth import require_csrf, require_role
from app.api.dependencies.config import get_runtime_config_service
from app.application.config.runtime_config_service import RuntimeConfigService
from app.domain.entities.admin_audit_log_entry import (
    AGENT_CONTACT_FILTER_UPDATED,
    AGENT_PAUSED,
    AGENT_RESUMED,
    AdminAuditLogEntry,
)
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.domain.entities.runtime_agent_config import RUNTIME_AGENT_CONFIG_ID, RuntimeAgentConfig
from app.domain.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.domain.rules.agent_gate import CONTACT_FILTER_MODES, FILTER_ALLOW, normalize_phone
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/admin/api", tags=["admin-agent-control"])

_MAX_PHONES = 500
_MIN_DIGITS = 8
_MAX_DIGITS = 15


class AgentControlResponse(BaseModel):
    agent_paused: bool
    paused_by: str | None
    paused_at: datetime | None
    contact_filter_mode: str
    contact_filter_phones: list[str]
    updated_at: datetime

    @classmethod
    def from_entity(cls, config: RuntimeAgentConfig) -> "AgentControlResponse":
        return cls(
            agent_paused=config.agent_paused,
            paused_by=config.paused_by,
            paused_at=config.paused_at,
            contact_filter_mode=config.contact_filter_mode,
            contact_filter_phones=list(config.contact_filter_phones),
            updated_at=config.updated_at,
        )


class AgentControlUpdateRequest(BaseModel):
    agent_paused: bool
    contact_filter_mode: str
    contact_filter_phones: list[str]


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


def _clean_phones(raw: list[str]) -> tuple[str, ...]:
    """Digits only, blanks dropped, duplicates removed keeping first-seen order."""
    if len(raw) > _MAX_PHONES:
        raise _bad_request(f"La lista admite hasta {_MAX_PHONES} números.")
    cleaned: list[str] = []
    for item in raw:
        if not item.strip():
            continue
        digits = normalize_phone(item)
        if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
            raise _bad_request(
                f"Número inválido: cada número debe tener entre {_MIN_DIGITS} y "
                f"{_MAX_DIGITS} dígitos (incluí el código de país)."
            )
        if digits not in cleaned:
            cleaned.append(digits)
    return tuple(cleaned)


@router.get("/agent-control", response_model=AgentControlResponse)
async def get_agent_control(
    _session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL, ADMIN_CLINIC, READ_ONLY)),
    runtime_config_service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> AgentControlResponse:
    config = await runtime_config_service.get_config()
    return AgentControlResponse.from_entity(config)


@router.put("/agent-control", response_model=AgentControlResponse)
async def update_agent_control(
    body: AgentControlUpdateRequest,
    session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL, ADMIN_CLINIC)),
    _csrf: SessionPayload = Depends(require_csrf),
    runtime_config_service: RuntimeConfigService = Depends(get_runtime_config_service),
    audit_log_repository: AdminAuditLogRepository = Depends(
        get_committing_admin_audit_log_repository
    ),
) -> AgentControlResponse:
    """Pause switch and contact filter. An emergency stop must not depend on a
    technical user, so `ADMIN_CLINIC` may also change it; `READ_ONLY` only reads.

    Every other config field (model, prompts, debounce) is preserved. Audit
    entries never carry phone numbers: they are patient data.
    """
    if body.contact_filter_mode not in CONTACT_FILTER_MODES:
        raise _bad_request("Modo de filtro inválido.")
    phones = _clean_phones(body.contact_filter_phones)
    if body.contact_filter_mode == FILTER_ALLOW and not phones:
        raise _bad_request(
            "El modo «Responder solo a estos números» requiere al menos un número: "
            "con la lista vacía el agente no le respondería a nadie."
        )

    existing = await runtime_config_service.get_config()
    now = datetime.now(UTC)
    pause_changed = body.agent_paused != existing.agent_paused
    filter_changed = (
        body.contact_filter_mode != existing.contact_filter_mode
        or phones != existing.contact_filter_phones
    )

    paused_by = existing.paused_by
    paused_at = existing.paused_at
    if pause_changed:
        paused_by = session.username if body.agent_paused else None
        paused_at = now if body.agent_paused else None

    updated = replace(
        existing,
        updated_at=now,
        updated_by=session.username,
        agent_paused=body.agent_paused,
        paused_by=paused_by,
        paused_at=paused_at,
        contact_filter_mode=body.contact_filter_mode,
        contact_filter_phones=phones,
    )
    if pause_changed or filter_changed:
        await runtime_config_service.save_config(updated)
    else:
        updated = existing

    actions: list[str] = []
    if pause_changed:
        actions.append(AGENT_PAUSED if body.agent_paused else AGENT_RESUMED)
    if filter_changed:
        actions.append(AGENT_CONTACT_FILTER_UPDATED)
    for action in actions:
        await audit_log_repository.save(
            AdminAuditLogEntry(
                id=str(uuid4()),
                admin_user_id=session.admin_user_id,
                username=session.username,
                action=action,
                resource_type="runtime_agent_config",
                resource_id=RUNTIME_AGENT_CONFIG_ID,
                success=True,
                created_at=now,
            )
        )

    return AgentControlResponse.from_entity(updated)
