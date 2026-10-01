"""The real-LLM branch of the eval stack, exercised the way production wires it.

`get_llm_provider()` is NOT replaced here: only the settings, the runtime-config
service (a Postgres-backed read in production) and the network layer are patched,
so a wiring mistake in the real branch fails this test instead of the first turn of
the production audit.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest

import app.infrastructure.llm.client as llm_client_module
from app.api.dependencies import gateways, internal_eval
from app.config.settings import Settings
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.llm.openai_compatible_llm_provider import OpenAICompatibleLLMProvider
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import make_runtime_config_service

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def real_llm_stack(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    settings = Settings(
        internal_eval_real_llm=True,
        llm_api_url="http://llm.invalid/v1",
        llm_api_key="test-key",
        openai_model="test-model",
        _env_file=None,
    )
    monkeypatch.setattr(internal_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(gateways, "get_settings", lambda: settings)
    monkeypatch.setattr(
        gateways, "get_runtime_config_service", lambda: make_runtime_config_service()
    )
    redis = InMemoryFakeRedis()
    monkeypatch.setattr(internal_eval, "get_shared_redis_client", lambda: redis)
    gateways._get_llm_client.cache_clear()
    gateways._get_real_llm_provider.cache_clear()
    internal_eval.get_eval_session_registry.cache_clear()

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        content = json.dumps({"intent": "unknown", "confidence": 0.1})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    original = httpx.AsyncClient

    def patched(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", patched)
    yield captured
    gateways._get_llm_client.cache_clear()
    gateways._get_real_llm_provider.cache_clear()


def test_the_real_branch_wires_the_openai_compatible_provider(real_llm_stack):
    use_case = internal_eval.get_evaluate_chat_turn_use_case()

    llm = use_case._agent_invoker._llm_provider  # type: ignore[attr-defined]
    assert isinstance(llm, OpenAICompatibleLLMProvider)


@pytest.mark.asyncio
async def test_a_turn_with_the_real_provider_completes_and_calls_the_llm_endpoint(
    real_llm_stack,
):
    provider = internal_eval.get_eval_use_case_provider()
    conversation_id = ConversationId("eval-real-llm-turn-1")

    result = await provider(conversation_id).execute(conversation_id, "quiero un turno", now=_NOW)

    assert result.agent_run is not None
    assert result.agent_run.status != "failed"
    assert result.reply_text
    assert real_llm_stack, "the real provider never reached the LLM endpoint"
    assert real_llm_stack[0].url.host == "llm.invalid"
