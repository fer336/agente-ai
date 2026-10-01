from datetime import UTC, datetime

import pytest

from app.application.admin.evaluate_chat_turn import (
    EvalFlow,
    EvalOption,
    EvaluateChatTurnUseCase,
    eval_contact_id,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.flow_request import FlowRequest
from app.domain.value_objects.interactive_button import InteractiveButton
from app.domain.value_objects.list_message import ListMessage, ListRow
from app.domain.value_objects.location_request import LocationRequest
from app.domain.value_objects.phone_number import PhoneNumber
from app.infrastructure.agent.fake_agent_invoker import FakeAgentInvoker
from app.infrastructure.ycloud.fake_messaging_gateway import FakeYCloudMessagingGateway
from tests.fixtures.gateways import (
    make_agent_run_repository,
    make_contact_repository,
    make_conversation_repository,
    make_message_repository,
    make_node_execution_repository,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_agent_run, make_node_execution, make_tool_execution

_NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


def _use_case(agent_runs=None, node_executions=None, tool_executions=None, messaging_gateway=None):
    return EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=agent_runs or make_agent_run_repository(),
        node_executions=node_executions or make_node_execution_repository(),
        tool_executions=tool_executions or make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=messaging_gateway or FakeYCloudMessagingGateway(),
    )


@pytest.mark.asyncio
async def test_execute_creates_the_eval_contact_and_conversation_and_saves_the_inbound_message():
    conversations = make_conversation_repository()
    contacts = make_contact_repository()
    messages = make_message_repository()
    use_case = EvaluateChatTurnUseCase(
        conversations=conversations,
        contacts=contacts,
        messages=messages,
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "Cancelame el turno de mañana", now=_NOW)

    assert await contacts.get_by_id(eval_contact_id(ConversationId("eval-001"))) is not None
    conversation = await conversations.get_by_id(ConversationId("eval-001"))
    assert conversation is not None
    assert conversation.contact_id == eval_contact_id(ConversationId("eval-001"))
    saved_messages = await messages.get_by_conversation_id(ConversationId("eval-001"))
    assert [m.text for m in saved_messages] == ["Cancelame el turno de mañana"]


@pytest.mark.asyncio
async def test_execute_reuses_an_existing_conversation_without_duplicating_the_contact():
    conversations = make_conversation_repository()
    contacts = make_contact_repository()
    use_case = EvaluateChatTurnUseCase(
        conversations=conversations,
        contacts=contacts,
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "primer turno", now=_NOW)
    await use_case.execute(ConversationId("eval-001"), "segundo turno", now=_NOW)

    conversation = await conversations.get_by_id(ConversationId("eval-001"))
    assert conversation is not None


@pytest.mark.asyncio
async def test_execute_calls_the_agent_invoker_with_the_saved_message_id():
    invoker = FakeAgentInvoker()
    use_case = EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=invoker,
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-001"), "quiero un turno", now=_NOW)

    assert len(invoker.calls) == 1
    conversation_id, message_ids, user_message, button_payload = invoker.calls[0]
    assert conversation_id == ConversationId("eval-001")
    assert len(message_ids) == 1
    assert user_message == "quiero un turno"
    assert button_payload is None


@pytest.mark.asyncio
async def test_execute_returns_the_latest_agent_run_trace_and_the_last_sent_reply():
    agent_runs = make_agent_run_repository()
    node_executions = make_node_execution_repository()
    tool_executions = make_tool_execution_repository()
    messaging_gateway = FakeYCloudMessagingGateway()

    # Simulates what a real `LangGraphAgentInvoker.handle()` run would have
    # left behind — `FakeAgentInvoker` itself is a no-op recorder.
    await agent_runs.save(make_agent_run(id_="run-1", conversation_id="eval-001"))
    await node_executions.save(make_node_execution(id_="ne-1", agent_run_id="run-1"))
    await tool_executions.save(make_tool_execution(id_="te-1", agent_run_id="run-1"))
    await messaging_gateway.send_text_message(
        PhoneNumber("+5490000000000"), "¿Qué horario preferís?"
    )

    use_case = _use_case(agent_runs, node_executions, tool_executions, messaging_gateway)

    result = await use_case.execute(ConversationId("eval-001"), "quiero un turno", now=_NOW)

    assert result.reply_text == "¿Qué horario preferís?"
    assert result.agent_run is not None
    assert result.agent_run.id == "run-1"
    assert [ne.id for ne in result.node_executions] == ["ne-1"]
    assert [te.id for te in result.tool_executions] == ["te-1"]


@pytest.mark.parametrize(
    ("collection_name", "entry", "expected_reply"),
    [
        (
            "sent_buttons",
            (PhoneNumber("+5490000000000"), "Elegí una opción", [], None),
            "Elegí una opción",
        ),
        (
            "sent_flows",
            (
                PhoneNumber("+5490000000000"),
                "Completá tus datos",
                FlowRequest(flow_id="f", flow_screen_id="s", flow_cta="c", flow_token="t"),
            ),
            "Completá tus datos",
        ),
        (
            "sent_lists",
            (
                PhoneNumber("+5490000000000"),
                "Seleccioná una alternativa",
                ListMessage(button_label="Ver", rows=[ListRow(id="r", title="t")]),
            ),
            "Seleccioná una alternativa",
        ),
    ],
)
@pytest.mark.asyncio
async def test_execute_returns_text_from_interactive_replies(
    collection_name, entry, expected_reply
):
    messaging_gateway = FakeYCloudMessagingGateway()
    getattr(messaging_gateway, collection_name).append(entry)
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-interactive"), "hola", now=_NOW)

    assert result.reply_text == expected_reply


@pytest.mark.asyncio
async def test_execute_returns_no_reply_and_empty_trace_when_the_invoker_produced_nothing():
    use_case = _use_case()

    result = await use_case.execute(ConversationId("eval-002"), "hola", now=_NOW)

    assert result.reply_text is None
    assert result.agent_run is None
    assert result.node_executions == []
    assert result.tool_executions == []


_PHONE = PhoneNumber("+5490000000000")


@pytest.mark.asyncio
async def test_execute_exposes_reply_buttons_with_their_ids_and_titles():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_buttons(
        _PHONE,
        "¿Es tu primera cita?",
        [
            InteractiveButton(id="FIRST_VISIT_CONFIRM", title="✅ Confirmar"),
            InteractiveButton(id="FIRST_VISIT_CANCEL", title="❌ Cancelar"),
        ],
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-buttons"), "hola", now=_NOW)

    assert result.reply_kind == "buttons"
    assert result.buttons == [
        EvalOption(id="FIRST_VISIT_CONFIRM", title="✅ Confirmar"),
        EvalOption(id="FIRST_VISIT_CANCEL", title="❌ Cancelar"),
    ]
    assert result.list_rows == []
    assert result.flow is None
    assert result.image_url is None


@pytest.mark.asyncio
async def test_execute_exposes_the_image_url_of_an_image_button_reply():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_buttons(
        _PHONE,
        "📍 Así llegás a Smiling Pilar",
        [InteractiveButton(id="LOCATION_DETAIL", title="Cómo llegar")],
        image_url="https://example.com/clinic.jpg",
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-image"), "dónde queda", now=_NOW)

    assert result.reply_kind == "buttons"
    assert result.image_url == "https://example.com/clinic.jpg"


@pytest.mark.asyncio
async def test_execute_exposes_list_rows_flattened_across_sections():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_list(
        _PHONE,
        "Elegí una especialidad",
        ListMessage(
            button_label="Ver opciones",
            rows=[
                ListRow(id="SPECIALTY:1", title="Ortodoncia", description="Brackets"),
                ListRow(id="SPECIALTY:2", title="Endodoncia"),
            ],
        ),
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-list"), "hola", now=_NOW)

    assert result.reply_kind == "list"
    assert result.list_rows == [
        EvalOption(id="SPECIALTY:1", title="Ortodoncia", description="Brackets"),
        EvalOption(id="SPECIALTY:2", title="Endodoncia"),
    ]
    assert result.buttons == []


@pytest.mark.asyncio
async def test_execute_exposes_the_flow_marker():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_flow(
        _PHONE,
        "Completá tus datos",
        FlowRequest(
            flow_id="flow-123", flow_screen_id="SCREEN_A", flow_cta="Completar", flow_token="t"
        ),
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-flow"), "hola", now=_NOW)

    assert result.reply_kind == "flow"
    assert result.flow == EvalFlow(flow_id="flow-123", screen_id="SCREEN_A", cta="Completar")


@pytest.mark.asyncio
async def test_execute_reports_a_plain_text_reply_kind_without_options():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_text_message(_PHONE, "Hola")
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-text"), "hola", now=_NOW)

    assert result.reply_kind == "text"
    assert result.buttons == []
    assert result.list_rows == []
    assert result.flow is None


@pytest.mark.asyncio
async def test_execute_reports_no_reply_kind_when_nothing_was_sent():
    result = await _use_case().execute(ConversationId("eval-none"), "hola", now=_NOW)

    assert result.reply_kind is None


@pytest.mark.asyncio
async def test_execute_reports_the_last_message_sent_not_a_fixed_kind_priority():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_buttons(
        _PHONE, "¿Qué hacemos?", [InteractiveButton(id="MENU_MAIN", title="Menú principal")]
    )
    await messaging_gateway.send_text_message(_PHONE, "Resumen final")
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-order-1"), "hola", now=_NOW)

    assert result.reply_kind == "text"
    assert result.reply_text == "Resumen final"
    assert result.buttons == []


@pytest.mark.asyncio
async def test_execute_reports_a_list_sent_after_buttons_as_the_reply():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_buttons(
        _PHONE, "Antes", [InteractiveButton(id="MENU_MAIN", title="Menú principal")]
    )
    await messaging_gateway.send_list(
        _PHONE,
        "Elegí",
        ListMessage(button_label="Ver", rows=[ListRow(id="SPECIALTY:1", title="Ortodoncia")]),
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-order-2"), "hola", now=_NOW)

    assert result.reply_kind == "list"
    assert result.reply_text == "Elegí"
    assert [r.id for r in result.list_rows] == ["SPECIALTY:1"]
    assert result.buttons == []


@pytest.mark.asyncio
async def test_execute_reports_a_location_reply():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_location(
        _PHONE, LocationRequest(latitude=-34.6, longitude=-58.4, name="Clínica", address="Calle 1")
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    result = await use_case.execute(ConversationId("eval-location"), "hola", now=_NOW)

    assert result.reply_kind == "location"
    assert result.reply_text is None


class _RaisingInvoker:
    def __init__(self, messaging_gateway: FakeYCloudMessagingGateway) -> None:
        self._gateway = messaging_gateway

    async def handle(self, conversation_id, message_ids, user_message, button_payload) -> None:
        await self._gateway.send_text_message(_PHONE, "reply sent before the crash")
        raise RuntimeError("agent exploded")


@pytest.mark.asyncio
async def test_execute_clears_captured_replies_even_when_the_invoker_raises():
    messaging_gateway = FakeYCloudMessagingGateway()
    use_case = EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=_RaisingInvoker(messaging_gateway),
        messaging_gateway=messaging_gateway,
    )

    with pytest.raises(RuntimeError):
        await use_case.execute(ConversationId("eval-crash"), "hola", now=_NOW)

    assert messaging_gateway.sent_messages == []
    assert messaging_gateway.sent_log == []


@pytest.mark.asyncio
async def test_each_conversation_gets_its_own_eval_contact():
    contacts = make_contact_repository()
    use_case = EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=contacts,
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=FakeAgentInvoker(),
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(ConversationId("eval-a"), "hola", now=_NOW)
    await use_case.execute(ConversationId("eval-b"), "hola", now=_NOW)

    assert await contacts.get_by_id(eval_contact_id(ConversationId("eval-a"))) is not None
    assert await contacts.get_by_id(eval_contact_id(ConversationId("eval-b"))) is not None
    assert eval_contact_id(ConversationId("eval-a")) != eval_contact_id(ConversationId("eval-b"))


@pytest.mark.asyncio
async def test_execute_forwards_the_button_payload_to_the_agent_invoker():
    invoker = FakeAgentInvoker()
    use_case = EvaluateChatTurnUseCase(
        conversations=make_conversation_repository(),
        contacts=make_contact_repository(),
        messages=make_message_repository(),
        agent_runs=make_agent_run_repository(),
        node_executions=make_node_execution_repository(),
        tool_executions=make_tool_execution_repository(),
        agent_invoker=invoker,
        messaging_gateway=FakeYCloudMessagingGateway(),
    )

    await use_case.execute(
        ConversationId("eval-tap"), "✅ Confirmar", now=_NOW, button_payload="FIRST_VISIT_CONFIRM"
    )

    assert invoker.calls[0][2:] == ("✅ Confirmar", "FIRST_VISIT_CONFIRM")


@pytest.mark.asyncio
async def test_execute_consumes_the_captured_reply_so_the_next_turn_starts_clean():
    messaging_gateway = FakeYCloudMessagingGateway()
    await messaging_gateway.send_buttons(
        _PHONE, "¿Qué hacemos?", [InteractiveButton(id="MENU_MAIN", title="Menú principal")]
    )
    use_case = _use_case(messaging_gateway=messaging_gateway)

    first = await use_case.execute(ConversationId("eval-drain"), "hola", now=_NOW)
    second = await use_case.execute(ConversationId("eval-drain"), "chau", now=_NOW)

    assert first.reply_text == "¿Qué hacemos?"
    assert second.reply_text is None
    assert second.reply_kind is None
    assert second.buttons == []
