import pytest

from app.domain.entities.tool_execution import COMPLETED, FAILED
from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.observability.trace_context import TraceContext, use_trace_context
from app.infrastructure.ycloud.exceptions import YCloudAPIError
from app.infrastructure.ycloud.messaging_gateway import YCloudMessagingGateway
from tests.fixtures.gateways import (
    make_error_repository,
    make_error_service,
    make_tool_execution_repository,
)


class _StubYCloudClient:
    def __init__(self) -> None:
        self.text_calls: list[tuple[str, str]] = []
        self.button_calls: list[tuple[str, str, list[InteractiveButton]]] = []

    async def send_text(self, to: str, text: str) -> str:
        self.text_calls.append((to, text))
        return "wamid.stub-1"

    async def send_buttons(self, to: str, text: str, buttons: list[InteractiveButton]) -> str:
        self.button_calls.append((to, text, buttons))
        return "wamid.stub-2"


@pytest.mark.asyncio
async def test_send_text_message_delegates_to_client_with_stringified_phone():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)

    external_id = await gateway.send_text_message(PhoneNumber("+5491122334455"), "Hola")

    assert client.text_calls == [("+5491122334455", "Hola")]
    assert external_id == "wamid.stub-1"


@pytest.mark.asyncio
async def test_send_buttons_delegates_to_client_with_stringified_phone():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    buttons = [InteractiveButton(id="confirm", title="Confirmar")]

    external_id = await gateway.send_buttons(
        PhoneNumber("+5491122334455"), "¿Confirmás?", buttons
    )

    assert client.button_calls == [("+5491122334455", "¿Confirmás?", buttons)]
    assert external_id == "wamid.stub-2"


def test_ycloud_messaging_gateway_satisfies_messaging_gateway_protocol():
    assert isinstance(YCloudMessagingGateway(_StubYCloudClient()), MessagingGateway)


@pytest.mark.asyncio
async def test_send_text_message_records_a_completed_tool_execution_without_the_raw_text():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    tool_execution_repository = make_tool_execution_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(),
    )

    with use_trace_context(context):
        await gateway.send_text_message(PhoneNumber("+5491122334455"), "Juan Perez, 30123456")

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    execution = executions[0]
    assert execution.tool_name == "SendTextMessageTool"
    assert execution.provider == "ycloud"
    assert execution.status == COMPLETED
    assert execution.response_summary == "external_message_id=wamid.stub-1"
    assert "+5491122334455" not in execution.request_summary
    assert "Juan Perez" not in execution.request_summary
    assert "30123456" not in execution.request_summary


@pytest.mark.asyncio
async def test_send_buttons_records_a_failed_tool_execution_with_http_status():
    class _FailingYCloudClient(_StubYCloudClient):
        async def send_buttons(self, to, text, buttons):
            raise YCloudAPIError("YCloud API returned 401: unauthorized", status_code=401)

    gateway = YCloudMessagingGateway(_FailingYCloudClient())
    tool_execution_repository = make_tool_execution_repository()
    error_repository = make_error_repository()
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=tool_execution_repository,
        error_service=make_error_service(error_repository),
    )
    buttons = [InteractiveButton(id="confirm", title="Confirmar")]

    with use_trace_context(context), pytest.raises(YCloudAPIError):
        await gateway.send_buttons(PhoneNumber("+5491122334455"), "¿Confirmás?", buttons)

    executions = await tool_execution_repository.get_by_agent_run_id("run-1")
    assert len(executions) == 1
    assert executions[0].tool_name == "SendButtonsTool"
    assert executions[0].status == FAILED
    assert executions[0].http_status == "401"
    error = await error_repository.get_by_id(executions[0].error_id)
    assert error is not None
    assert error.error_type == "ycloud_auth_error"
    assert error.severity == "CRITICAL"
