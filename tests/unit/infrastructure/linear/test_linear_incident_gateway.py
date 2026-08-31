import httpx
import pytest

import app.infrastructure.linear.linear_incident_gateway as gateway_module
from app.infrastructure.linear.linear_incident_gateway import LinearIncidentGateway


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


def _gateway() -> LinearIncidentGateway:
    return LinearIncidentGateway(
        base_url="https://api.linear.app", api_key="secret-key", team_id="team-1",
        timeout_seconds=10,
    )


@pytest.mark.asyncio
async def test_create_issue_sends_authorization_header_and_returns_the_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_payload = {"success": True, "issue": {"identifier": "CLI-42"}}
    captured = _capture_requests(
        monkeypatch, httpx.Response(200, json={"data": {"issueCreate": issue_payload}})
    )

    issue_id = await _gateway().create_issue(
        title="Dentalink auth failure", description="details", priority="urgent"
    )

    assert issue_id == "CLI-42"
    assert len(captured) == 1
    request = captured[0]
    assert request.url == "https://api.linear.app/graphql"
    assert request.headers["authorization"] == "secret-key"


@pytest.mark.asyncio
async def test_add_comment_posts_a_comment_create_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_requests(
        monkeypatch, httpx.Response(200, json={"data": {"commentCreate": {"success": True}}})
    )

    await _gateway().add_comment("CLI-42", "still happening")

    assert len(captured) == 1
    assert b"CLI-42" in captured[0].content


@pytest.mark.asyncio
async def test_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_requests(monkeypatch, httpx.Response(401, text="unauthorized"))

    with pytest.raises(RuntimeError):
        await _gateway().create_issue(title="t", description="d", priority="urgent")


@pytest.mark.asyncio
async def test_raises_when_the_response_carries_graphql_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_requests(
        monkeypatch, httpx.Response(200, json={"errors": [{"message": "invalid team"}]})
    )

    with pytest.raises(RuntimeError):
        await _gateway().create_issue(title="t", description="d", priority="urgent")


@pytest.mark.asyncio
async def test_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", patched_async_client)

    with pytest.raises(RuntimeError):
        await _gateway().create_issue(title="t", description="d", priority="urgent")


@pytest.mark.asyncio
async def test_close_issue_is_a_documented_placeholder() -> None:
    with pytest.raises(NotImplementedError):
        await _gateway().close_issue("CLI-42")
