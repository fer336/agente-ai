from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.admin import (
    get_committing_admin_audit_log_repository,
    get_return_to_agent_use_case,
)
from app.application.conversations.return_to_agent import ReturnConversationToAgentUseCase
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_audit_log_entry import CONVERSATION_RETURNED_TO_AGENT
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import create_session_token
from app.infrastructure.chatwoot.fake_gateway import FakeChatwootGateway
from app.infrastructure.database.fake_admin_audit_log_repository import (
    FakeAdminAuditLogRepository,
)
from app.infrastructure.database.fake_chatwoot_mapping_repository import (
    FakeChatwootMappingRepository,
)
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.main import app
from tests.fixtures.seed_objects import make_conversation

_SECRET = "test-admin-secret"
_TTL = 3600
_ID = "ycloud-+5491122334455"
_URL = f"/admin/api/conversations/{_ID}/return-to-agent"


def _override_settings() -> Settings:
    return Settings(admin_session_secret=_SECRET, admin_session_ttl_seconds=_TTL, _env_file=None)


@pytest.fixture(autouse=True)
async def _deps():
    conversations = FakeConversationRepository()
    await conversations.save(make_conversation(id_=_ID, mode="human", input_state="HUMAN"))
    audit = FakeAdminAuditLogRepository()
    use_case = ReturnConversationToAgentUseCase(
        conversations, FakeChatwootMappingRepository(), FakeChatwootGateway()
    )
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_return_to_agent_use_case] = lambda: use_case
    app.dependency_overrides[get_committing_admin_audit_log_repository] = lambda: audit
    yield conversations, audit
    app.dependency_overrides.clear()


def _cookies(role: str) -> dict[str, str]:
    token, csrf = create_session_token(
        "admin-1", "staff1", role, _SECRET, _TTL, now=datetime.now(UTC)
    )
    return {"admin_session": token, "admin_csrf": csrf}


async def _post(cookies: dict[str, str] | None = None, csrf: bool = True, url: str = _URL):
    headers = {"x-csrf-token": cookies["admin_csrf"]} if csrf and cookies else {}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.post(url, headers=headers)


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected():
    assert (await _post()).status_code == 401


@pytest.mark.asyncio
async def test_read_only_role_cannot_return_a_conversation():
    assert (await _post(_cookies(READ_ONLY))).status_code == 403


@pytest.mark.asyncio
async def test_a_missing_csrf_token_is_rejected():
    assert (await _post(_cookies(ADMIN_CLINIC), csrf=False)).status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_TECHNICAL, ADMIN_CLINIC])
async def test_admin_roles_hand_the_conversation_back_and_the_change_is_audited(role: str, _deps):
    conversations, audit = _deps

    response = await _post(_cookies(role))

    assert response.status_code == 200
    assert response.json() == {"conversation_id": _ID, "mode": "agent"}
    conversation = await conversations.get_by_id(ConversationId(_ID))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert [entry.action for entry in audit.all()] == [CONVERSATION_RETURNED_TO_AGENT]
    assert audit.all()[0].resource_id == _ID


@pytest.mark.asyncio
async def test_an_unknown_conversation_is_a_404_and_nothing_is_audited(_deps):
    _, audit = _deps

    response = await _post(
        _cookies(ADMIN_TECHNICAL),
        url="/admin/api/conversations/ycloud-+5490000000000/return-to-agent",
    )

    assert response.status_code == 404
    assert audit.all() == []
