from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.internal_eval import get_eval_use_case_provider
from app.application.admin.evaluate_chat_turn import ChatTurnResult, EvalFlow, EvalOption
from app.config.settings import Settings, get_settings
from app.domain.entities.admin_user import ADMIN_CLINIC, ADMIN_TECHNICAL, READ_ONLY
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.auth.session_tokens import create_session_token
from app.main import app

_SECRET = "test-admin-secret"
_TTL = 3600


class _StubUseCase:
    def __init__(self, result: ChatTurnResult) -> None:
        self.result = result
        self.calls: list[tuple[ConversationId, str, str | None]] = []

    async def execute(self, conversation_id, message, now, button_payload=None):
        self.calls.append((conversation_id, message, button_payload))
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


async def _post_eval_chat(
    cookies: dict[str, str] | None = None, extra: dict[str, str] | None = None
):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies or {}
    ) as client:
        return await client.post(
            "/internal/eval/chat",
            json={
                "conversation_id": "eval-001",
                "message": "Cancelame el turno de mañana",
                **(extra or {}),
            },
        )


@pytest.mark.asyncio
async def test_disabled_by_default_returns_404_even_for_an_authenticated_caller(
    stub_use_case: _StubUseCase,
):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=False)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_disabled_returns_404_even_when_unauthenticated(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=False)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=None)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_enabled_but_unauthenticated_is_rejected(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=None)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [ADMIN_CLINIC, READ_ONLY])
async def test_enabled_but_non_technical_role_is_forbidden(stub_use_case: _StubUseCase, role: str):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies(role))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert stub_use_case.calls == []


@pytest.mark.asyncio
async def test_enabled_and_authenticated_evaluates_the_turn(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["reply_text"] == "¿Qué horario preferís?"
    assert stub_use_case.calls == [
        (ConversationId("eval-001"), "Cancelame el turno de mañana", None)
    ]
    body = response.json()
    assert body["reply_kind"] is None
    assert body["buttons"] == []
    assert body["list_rows"] == []
    assert body["flow"] is None


@pytest.mark.asyncio
async def test_button_payload_is_threaded_into_the_use_case(stub_use_case: _StubUseCase):
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(
            cookies=_session_cookies(), extra={"button_payload": "FIRST_VISIT_CONFIRM"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub_use_case.calls[0][2] == "FIRST_VISIT_CONFIRM"


@pytest.mark.asyncio
async def test_response_exposes_interactive_options():
    stub = _StubUseCase(
        ChatTurnResult(
            reply_text="¿Es tu primera cita?",
            agent_run=None,
            node_executions=[],
            tool_executions=[],
            reply_kind="buttons",
            buttons=[EvalOption(id="FIRST_VISIT_CONFIRM", title="✅ Confirmar")],
            list_rows=[EvalOption(id="SPECIALTY:1", title="Ortodoncia", description="Brackets")],
            flow=EvalFlow(flow_id="f1", screen_id="S1", cta="Completar"),
        )
    )
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub
    try:
        response = await _post_eval_chat(cookies=_session_cookies())
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert body["reply_kind"] == "buttons"
    assert body["buttons"] == [{"id": "FIRST_VISIT_CONFIRM", "title": "✅ Confirmar"}]
    assert body["list_rows"] == [
        {"id": "SPECIALTY:1", "title": "Ortodoncia", "description": "Brackets"}
    ]
    assert body["flow"] == {"flow_id": "f1", "screen_id": "S1", "cta": "Completar"}


@pytest.mark.asyncio
async def test_an_empty_button_payload_is_treated_as_no_tap(stub_use_case: _StubUseCase):
    """Promptfoo templates an unset var as an empty string; that must not reach
    the agent as a (non-null) button tap.
    """
    app.dependency_overrides[get_settings] = lambda: _override_settings(internal_eval_enabled=True)
    app.dependency_overrides[get_eval_use_case_provider] = lambda: lambda _cid: stub_use_case
    try:
        response = await _post_eval_chat(cookies=_session_cookies(), extra={"button_payload": ""})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert stub_use_case.calls[0][2] is None
