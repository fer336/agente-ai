import pytest

from app.domain.entities.tool_execution import COMPLETED, FAILED
from app.domain.repositories.gateways import MessagingGateway
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.location_request import LocationRequest
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
        self.button_calls: list[tuple[str, str, list[InteractiveButton], str | None]] = []
        self.flow_calls: list[tuple[str, str, str, str, str, str]] = []
        self.location_calls: list[tuple[str, float, float, str, str | None]] = []
        self.list_calls: list[tuple[str, str, str, list[ListRow], str | None]] = []
        self.contacts: dict[str, dict[str, object]] = {}

    async def send_text(self, to: str, text: str) -> str:
        self.text_calls.append((to, text))
        return "wamid.stub-1"

    async def send_buttons(
        self,
        to: str,
        text: str,
        buttons: list[InteractiveButton],
        image_url: str | None = None,
    ) -> str:
        self.button_calls.append((to, text, buttons, image_url))
        return "wamid.stub-2"

    async def send_flow(
        self,
        to: str,
        body_text: str,
        flow_id: str,
        flow_screen_id: str,
        flow_cta: str,
        flow_token: str,
    ) -> str:
        self.flow_calls.append((to, body_text, flow_id, flow_screen_id, flow_cta, flow_token))
        return "wamid.stub-3"

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str,
        address: str | None = None,
    ) -> str:
        self.location_calls.append((to, latitude, longitude, name, address))
        return "wamid.stub-4"

    async def send_list(
        self,
        to: str,
        text: str,
        button_label: str,
        rows: list[ListRow],
        section_title: str | None = None,
    ) -> str:
        self.list_calls.append((to, text, button_label, rows, section_title))
        return "wamid.stub-5"

    async def get_contact(self, contact_id: str) -> dict[str, object]:
        return self.contacts.get(contact_id, {})


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

    external_id = await gateway.send_buttons(PhoneNumber("+5491122334455"), "¿Confirmás?", buttons)

    assert client.button_calls == [("+5491122334455", "¿Confirmás?", buttons, None)]
    assert external_id == "wamid.stub-2"


@pytest.mark.asyncio
async def test_send_buttons_forwards_the_image_url_to_the_client():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    buttons = [InteractiveButton(id="confirm", title="Confirmar")]

    await gateway.send_buttons(
        PhoneNumber("+5491122334455"),
        "¡Hola!",
        buttons,
        image_url="https://example.com/logo.png",
    )

    assert client.button_calls == [
        ("+5491122334455", "¡Hola!", buttons, "https://example.com/logo.png")
    ]


@pytest.mark.asyncio
async def test_send_flow_delegates_to_client_with_stringified_phone():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    flow = FlowRequest(
        flow_id="flow-1",
        flow_screen_id="VERIFICACION",
        flow_cta="Completar",
        flow_token="ycloud-+5491122334455",
    )

    external_id = await gateway.send_flow(
        PhoneNumber("+5491122334455"), "Verificá tus datos", flow
    )

    assert client.flow_calls == [
        (
            "+5491122334455",
            "Verificá tus datos",
            "flow-1",
            "VERIFICACION",
            "Completar",
            "ycloud-+5491122334455",
        )
    ]
    assert external_id == "wamid.stub-3"


@pytest.mark.asyncio
async def test_send_location_delegates_to_client_with_stringified_phone():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    location = LocationRequest(
        latitude=-34.437762,
        longitude=-58.7917857,
        name="Smiling Pilar",
        address="Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires",
    )

    external_id = await gateway.send_location(PhoneNumber("+5491122334455"), location)

    assert client.location_calls == [
        (
            "+5491122334455",
            -34.437762,
            -58.7917857,
            "Smiling Pilar",
            "Las Camelias 3324 Ofi 207, B1669 Pilar, Buenos Aires",
        )
    ]
    assert external_id == "wamid.stub-4"


@pytest.mark.asyncio
async def test_send_list_delegates_to_client_with_stringified_phone():
    client = _StubYCloudClient()
    gateway = YCloudMessagingGateway(client)
    rows = [ListRow(id="MENU_CREATE", title="Agendar una cita")]
    list_message = ListMessage(
        button_label="Elegí una opción", rows=rows, section_title="Menú principal"
    )

    external_id = await gateway.send_list(
        PhoneNumber("+5491122334455"), "¿En qué te puedo ayudar?", list_message
    )

    assert client.list_calls == [
        (
            "+5491122334455",
            "¿En qué te puedo ayudar?",
            "Elegí una opción",
            rows,
            "Menú principal",
        )
    ]
    assert external_id == "wamid.stub-5"


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
        async def send_buttons(self, to, text, buttons, image_url=None):
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


@pytest.mark.asyncio
async def test_get_contact_phone_returns_the_resolved_phone_number():
    client = _StubYCloudClient()
    client.contacts["contact-1"] = {"id": "contact-1", "phoneNumber": "+5491122334455"}
    gateway = YCloudMessagingGateway(client)

    phone = await gateway.get_contact_phone("contact-1")

    assert phone == PhoneNumber("+5491122334455")


@pytest.mark.asyncio
async def test_get_contact_phone_returns_none_when_phone_number_missing():
    client = _StubYCloudClient()
    client.contacts["contact-1"] = {"id": "contact-1"}
    gateway = YCloudMessagingGateway(client)

    assert await gateway.get_contact_phone("contact-1") is None


@pytest.mark.asyncio
async def test_get_contact_phone_returns_none_when_phone_number_is_invalid():
    client = _StubYCloudClient()
    client.contacts["contact-1"] = {"id": "contact-1", "phoneNumber": "not-a-phone"}
    gateway = YCloudMessagingGateway(client)

    assert await gateway.get_contact_phone("contact-1") is None
