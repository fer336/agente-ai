import httpx
import pytest

import app.infrastructure.transcription.groq_transcription_gateway as gateway_module
from app.infrastructure.observability.trace_context import TraceContext, use_trace_context
from app.infrastructure.transcription.exceptions import (
    TranscriptionAPIError,
    TranscriptionAuthError,
    TranscriptionTimeoutError,
)
from app.infrastructure.transcription.groq_transcription_gateway import (
    GroqTranscriptionGateway,
)
from tests.fixtures.gateways import make_error_service, make_tool_execution_repository


def _capture_requests(monkeypatch: pytest.MonkeyPatch, response: httpx.Response):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", patched_async_client)
    return captured


@pytest.fixture
def audio_path(tmp_path) -> str:
    path = tmp_path / "audio.ogg"
    path.write_bytes(b"fake-ogg-bytes")
    return str(path)


@pytest.mark.asyncio
async def test_sends_bearer_auth_and_model_and_returns_text(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    captured = _capture_requests(
        monkeypatch, httpx.Response(200, json={"text": "hola quiero un turno"})
    )
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )

    result = await gateway.transcribe(audio_path, "audio/ogg")

    assert result == "hola quiero un turno"
    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert b"whisper-large-v3-turbo" in request.content


@pytest.mark.asyncio
async def test_raises_auth_error_on_401(monkeypatch: pytest.MonkeyPatch, audio_path: str) -> None:
    _capture_requests(monkeypatch, httpx.Response(401, text="unauthorized"))
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="bad-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )

    with pytest.raises(TranscriptionAuthError):
        await gateway.transcribe(audio_path, "audio/ogg")


@pytest.mark.asyncio
async def test_raises_api_error_on_other_non_2xx(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    _capture_requests(monkeypatch, httpx.Response(400, text="bad request"))
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )

    with pytest.raises(TranscriptionAPIError) as exc_info:
        await gateway.transcribe(audio_path, "audio/ogg")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_raises_timeout_error(monkeypatch: pytest.MonkeyPatch, audio_path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", patched_async_client)
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )

    with pytest.raises(TranscriptionTimeoutError):
        await gateway.transcribe(audio_path, "audio/ogg")


@pytest.mark.asyncio
async def test_auth_error_records_a_failed_tool_execution_with_classified_error(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    _capture_requests(monkeypatch, httpx.Response(403, text="forbidden"))
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="bad-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )
    tool_execution_repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(),
    )

    with use_trace_context(context), pytest.raises(TranscriptionAuthError):
        await gateway.transcribe(audio_path, "audio/ogg")

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].http_status == "auth_error"


@pytest.mark.asyncio
async def test_api_error_records_the_http_status_code(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    _capture_requests(monkeypatch, httpx.Response(400, text="bad request"))
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )
    tool_execution_repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(),
    )

    with use_trace_context(context), pytest.raises(TranscriptionAPIError):
        await gateway.transcribe(audio_path, "audio/ogg")

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].http_status == "400"


@pytest.mark.asyncio
async def test_timeout_error_records_the_timeout_http_status(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", patched_async_client)
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )
    tool_execution_repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(),
    )

    with use_trace_context(context), pytest.raises(TranscriptionTimeoutError):
        await gateway.transcribe(audio_path, "audio/ogg")

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].http_status == "timeout"


@pytest.mark.asyncio
async def test_missing_text_field_returns_empty_string(
    monkeypatch: pytest.MonkeyPatch, audio_path: str
) -> None:
    _capture_requests(monkeypatch, httpx.Response(200, json={}))
    gateway = GroqTranscriptionGateway(
        base_url="https://api.groq.com/openai/v1",
        api_key="secret-key",
        model="whisper-large-v3-turbo",
        timeout_seconds=45,
    )

    result = await gateway.transcribe(audio_path, "audio/ogg")

    assert result == ""
