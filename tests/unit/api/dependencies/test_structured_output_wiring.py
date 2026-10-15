"""`LLM_STRUCTURED_OUTPUT` must reach the request the real provider sends.

`get_llm_provider()` is not replaced: only the settings, the runtime-config service and the
network layer are patched, so a wiring mistake fails here instead of in production, where the
flag can only be switched on from the deployment secret.
"""

import json

import httpx
import pytest

import app.infrastructure.llm.client as llm_client_module
from app.api.dependencies import gateways
from app.config.settings import Settings
from tests.fixtures.gateways import make_runtime_config_service

_UNDERSTANDING = '{"intent": "unknown", "confidence": 0.1}'


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch):
    bodies: list[dict[str, object]] = []

    def _wire(*, structured_output: bool) -> list[dict[str, object]]:
        settings = Settings(
            llm_api_url="http://llm.invalid/v1",
            llm_api_key="test-key",
            openai_model="test-model",
            llm_structured_output=structured_output,
            _env_file=None,
        )
        monkeypatch.setattr(gateways, "get_settings", lambda: settings)
        monkeypatch.setattr(
            gateways, "get_runtime_config_service", lambda: make_runtime_config_service()
        )
        gateways._get_llm_client.cache_clear()
        gateways._get_real_llm_provider.cache_clear()

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": _UNDERSTANDING}}]})

        original = httpx.AsyncClient

        def patched(*args: object, **kwargs: object) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(llm_client_module.httpx, "AsyncClient", patched)
        return bodies

    yield _wire
    gateways._get_llm_client.cache_clear()
    gateways._get_real_llm_provider.cache_clear()


@pytest.mark.asyncio
async def test_the_flag_turns_the_json_schema_on_in_the_real_request(wire):
    bodies = wire(structured_output=True)

    await gateways.get_llm_provider().understand("quiero un turno", context={})

    response_format = bodies[0]["response_format"]
    assert response_format["type"] == "json_schema"  # type: ignore[index]
    assert response_format["json_schema"]["strict"] is True  # type: ignore[index]


@pytest.mark.asyncio
async def test_without_the_flag_the_real_request_has_no_response_format(wire):
    bodies = wire(structured_output=False)

    await gateways.get_llm_provider().understand("quiero un turno", context={})

    assert "response_format" not in bodies[0]
