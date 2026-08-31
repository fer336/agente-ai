from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.internal_eval import get_evaluate_chat_turn_use_case
from app.application.admin.evaluate_chat_turn import ChatTurnResult
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_TECHNICAL
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import create_session_token
from app.main import app

_SECRET = "test-admin-secret"
_TTL = 3600


class _StubUseCase:
    def __init__(self, result: ChatTurnResult) -> None:
        self.result = result
        self.calls: list[tuple[ConversationId, str]] = []

    async def execute(self, conversation_id, message, now):
        self.calls.append((conversation_id, message))
        return self.result


def _override_settings(*, internal_eval_enabled: bool) -> Settings:
    return Settings(
        admin_session_secret=_SECRET,
        admin_session_ttl_seconds=_TTL,
        internal_eval_enabled=internal_eval_enabled,
        _env_file=None,
    )


def _session_cookies(role: str = ADMIN_TECHNICAL) -> dict[str, str]:
    token, csrf = create_session_token(
        "admin-1", "tech1", role, _SECRET, _TTL, now=datetime.now(UTC)
    )
    return {"admin_session": token, "admin_csrf": csrf}


@pytest.fixture
def stub_use_case() -> _StubUseCase:
    return _StubUseCase(
        ChatTurnResult(
            reply_text="¿Qué horario preferís?",
            agent_run=None,
            node_executions=[],
            tool_executions=[],
        )
    )


async def _post_eval_chat(cookies: dict[str, str] | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.post(
            "/internal/eval/chat",
            json={"conversation_id": "eval-001", "message": "Cancelame el turno de mañana"},
        )


@pytest.mark.asyncio
async def test_disabled_by_default_returns_404_even_for_an_authenticated_caller(
    stub_use_case: _StubUseCase,
):
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        internal_eval_enabled=False
    )
    app.dependency_overrides[get_evaluate_chat_turn_use_case] = lambda: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_disabled_returns_404_even_when_unauthenticated(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        internal_eval_enabled=False
    )
    app.dependency_overrides[get_evaluate_chat_turn_use_case] = lambda: stub_use_case
    try:
        response = await _post_eval_chat(cookies=None)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_enabled_but_unauthenticated_is_rejected(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        internal_eval_enabled=True
    )
    app.dependency_overrides[get_evaluate_chat_turn_use_case] = lambda: stub_use_case
    try:
        response = await _post_eval_chat(cookies=None)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_enabled_and_authenticated_evaluates_the_turn(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        internal_eval_enabled=True
    )
    app.dependency_overrides[get_evaluate_chat_turn_use_case] = lambda: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["reply_text"] == "¿Qué horario preferís?"
    assert stub_use_case.calls == [(ConversationId("eval-001"), "Cancelame el turno de mañana")]
