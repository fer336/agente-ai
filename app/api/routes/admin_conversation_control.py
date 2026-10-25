from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies.admin import (
    get_committing_admin_audit_log_repository,
    get_return_to_agent_use_case,
)
from app.api.dependencies.auth import require_csrf, require_role
from app.application.conversations.return_to_agent import ReturnConversationToAgentUseCase
from app.domain.entities.admin_audit_log_entry import (
    CONVERSATION_RETURNED_TO_AGENT,
    AdminAuditLogEntry,
)
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL
from app.domain.repositories.admin_audit_log_repository import AdminAuditLogRepository
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import SessionPayload

router = APIRouter(prefix="/admin/api", tags=["admin-conversation-control"])


class ConversationModeResponse(BaseModel):
    conversation_id: str
    mode: str


@router.post(
    "/conversations/{conversation_id}/return-to-agent", response_model=ConversationModeResponse
)
async def return_conversation_to_agent(
    conversation_id: str,
    session: SessionPayload = Depends(require_role(ADMIN_TECHNICAL, ADMIN_CLINIC)),
    _csrf: SessionPayload = Depends(require_csrf),
    use_case: ReturnConversationToAgentUseCase = Depends(get_return_to_agent_use_case),
    audit_log_repository: AdminAuditLogRepository = Depends(
        get_committing_admin_audit_log_repository
    ),
) -> ConversationModeResponse:
    """Hands a conversation that staff took over back to the agent (same effect as `/bot`).

    Open to `ADMIN_CLINIC` as well as `ADMIN_TECHNICAL`: the clinic staff who takes a
    chat over must be able to give it back. `READ_ONLY` cannot. CSRF-checked and audited.
    """
    if not await use_case.execute(ConversationId(conversation_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")

    await audit_log_repository.save(
        AdminAuditLogEntry(
            id=str(uuid4()),
            admin_user_id=session.admin_user_id,
            username=session.username,
            action=CONVERSATION_RETURNED_TO_AGENT,
            resource_type="conversation",
            resource_id=conversation_id,
            success=True,
            created_at=datetime.now(UTC),
        )
    )
    return ConversationModeResponse(conversation_id=conversation_id, mode="agent")
