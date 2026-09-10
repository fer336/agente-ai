import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import (
    AGREEMENT_NODE,
    APPOINTMENT_NODE,
    CHECK_CONVERSATION_MODE_NODE,
    FALLBACK_NODE,
    HANDLE_ERROR_NODE,
    HANDOFF_NODE,
    RESOLVE_INTERACTION_NODE,
    SPECIALTIES_NODE,
    build_graph,
    build_state_reset_graph,
    compile_graph,
)
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.menu_payloads import MENU_ADMIN_PAYLOAD, MENU_MAIN_PAYLOAD
from app.domain.value_objects.welcome_menu import WELCOME_LIST, WELCOME_TEXT
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from app.infrastructure.dentalink.fake_agreement_gateway import FakeAgreementGateway
from app.infrastructure.dentalink.fake_dentalink_gateway import FakeDentalinkGateway
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from app.infrastructure.ycloud.fake_handoff_gateway import FakeYCloudHandoffGateway
from tests.fixtures.agent_state import make_agent_state
from tests.fixtures.fake_redis import InMemoryFakeRedis
from tests.fixtures.gateways import (
    make_error_repository,
    make_error_service,
    make_node_execution_repository,
    make_patient_gateway,
    make_proposal_repositories_provider,
    make_specialty_gateway,
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import (
    make_agreement,
    make_conversation,
    make_professional,
    make_specialty,
)


@pytest.mark.asyncio
async def test_no_availability_choices_and_main_menu_are_canonical():
    """Production graph regression: a terminal empty agenda gives the two
    explicit exits, and Main Menu restores the complete canonical welcome list.
    """
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(
        conversation_repository=conversation_repository,
        appointment_gateway=FakeDentalinkGateway(
            available_slots=[],
            professionals=[make_professional(id_="prof-1", specialty_id="cleaning")],
        ),
    )
    no_availability = await compiled.ainvoke(
        make_agent_state(
            conversation_id="conv-1",
            user_message="1",
            collected_data={
                "stage": "awaiting_professional_selection",
                "operation": "create_appointment",
                "chosen_specialty_id": "cleaning",
                "chosen_specialty_name": "Ortodoncia",
                "professional_options": [make_professional(id_="prof-1", specialty_id="cleaning")],
            },
        )
    )

    assert [(button.id, button.title) for button in no_availability["response_buttons"]] == [
        (MENU_ADMIN_PAYLOAD, "Administración"),
        (MENU_MAIN_PAYLOAD, "Menú principal"),
    ]

    main_menu = await compiled.ainvoke(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=MENU_MAIN_PAYLOAD,
            collected_data=no_availability["collected_data"],
        )
    )

    assert main_menu["response_text"] == WELCOME_TEXT
    assert main_menu["response_list"] == WELCOME_LIST
    assert main_menu["response_buttons"] is None


@pytest.mark.asyncio
async def test_no_availability_administration_choice_routes_to_handoff_and_human_mode():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(conversation_repository=conversation_repository)

    result = await compiled.ainvoke(
        make_agent_state(
            conversation_id="conv-1",
            button_payload=MENU_ADMIN_PAYLOAD,
            collected_data={"stage": "awaiting_no_availability_choice"},
        )
    )

    assert result["requires_handoff"] is True
    conversation = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert conversation is not None
    assert conversation.mode == "human"


def _build_graph(conversation_repository=None):
    return build_graph(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=FakeAgreementGateway(),
        specialty_gateway=make_specialty_gateway(),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversation_repository or FakeConversationRepository(),
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
    )


def _compile(
    conversation_repository=None,
    agreement_gateway=None,
    specialty_gateway=None,
    appointment_gateway=None,
    checkpointer=None,
    error_service=None,
):
    return compile_graph(
        appointment_gateway=appointment_gateway or FakeDentalinkGateway(),
        agreement_gateway=agreement_gateway or FakeAgreementGateway(),
        specialty_gateway=specialty_gateway or make_specialty_gateway(),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversation_repository or FakeConversationRepository(),
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=make_node_execution_repository(),
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=error_service or make_error_service(),
        checkpointer=checkpointer,
    )


def test_build_graph_wires_every_top_level_node():
    graph = _build_graph()

    assert {
        CHECK_CONVERSATION_MODE_NODE,
        RESOLVE_INTERACTION_NODE,
        APPOINTMENT_NODE,
        AGREEMENT_NODE,
        SPECIALTIES_NODE,
        HANDOFF_NODE,
        FALLBACK_NODE,
        HANDLE_ERROR_NODE,
    } <= set(graph.nodes)


@pytest.mark.asyncio
async def test_insurance_message_routes_through_the_agreement_node():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(
        conversation_repository=conversation_repository,
        agreement_gateway=FakeAgreementGateway(agreements=[make_agreement(name="OSDE")]),
    )

    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="¿Trabajan con OSDE?")
    )

    assert "OSDE" in result["response_text"]


@pytest.mark.asyncio
async def test_specialties_message_routes_through_the_specialties_node():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(
        conversation_repository=conversation_repository,
        specialty_gateway=make_specialty_gateway(
            specialties=[make_specialty(id_="spec-1", name="Ortodoncia")]
        ),
        appointment_gateway=FakeDentalinkGateway(
            professionals=[make_professional(specialty_id="spec-1")]
        ),
    )

    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="¿Qué especialidades tienen?")
    )

    # The catalog is now a paginated interactive list (emoji-prefixed rows),
    # not a plain text reply — assert on the list rows.
    list_message = result["response_list"]
    assert list_message is not None
    assert any("Ortodoncia" in row.title for row in list_message.rows)


@pytest.mark.asyncio
async def test_handoff_phrase_routes_through_the_handoff_node_and_flips_conversation_mode():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(conversation_repository=conversation_repository)

    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="Voy a llegar tarde")
    )

    assert result["requires_handoff"] is True
    updated = await conversation_repository.get_by_id(ConversationId("conv-1"))
    assert updated is not None
    assert updated.mode == "human"


@pytest.mark.asyncio
async def test_unrecognized_message_routes_through_fallback():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    compiled = _compile(conversation_repository=conversation_repository)

    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="asdkjaslkdj")
    )

    assert result["response_text"]
    assert [button.title for button in result["response_buttons"]] == [
        "Turnos",
        "Especialidades",
        "Administración",
    ]


@pytest.mark.asyncio
async def test_human_mode_conversation_ends_the_run_silently():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="human"))
    compiled = _compile(conversation_repository=conversation_repository)

    result = await compiled.ainvoke(make_agent_state(conversation_id="conv-1", user_message="hola"))

    assert result["response_text"] is None


@pytest.mark.asyncio
async def test_node_exception_routes_to_handle_error_and_returns_a_safe_reply():
    class _BrokenConversationRepository(FakeConversationRepository):
        async def get_by_id(self, conversation_id):
            raise RuntimeError("boom")

    error_repository = make_error_repository()
    compiled = _compile(
        conversation_repository=_BrokenConversationRepository(),
        error_service=make_error_service(error_repository),
    )

    result = await compiled.ainvoke(make_agent_state(conversation_id="conv-1"))

    assert "problema técnico" in result["response_text"]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_compiled_graph_records_node_executions_as_it_runs():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    node_execution_repository = make_node_execution_repository()
    compiled = compile_graph(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=FakeAgreementGateway(agreements=[make_agreement(name="OSDE")]),
        specialty_gateway=make_specialty_gateway(),
        handoff_gateway=FakeYCloudHandoffGateway(),
        llm_provider=FakeLLMProvider(),
        conversation_repository=conversation_repository,
        patient_gateway=make_patient_gateway(),
        proposal_repositories_provider=make_proposal_repositories_provider(),
        redis_client=InMemoryFakeRedis(),
        confirmation_timeout_seconds=120,
        node_execution_repository=node_execution_repository,
        agent_run_id="run-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
    )

    await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="¿Trabajan con OSDE?")
    )

    executions = await node_execution_repository.get_by_agent_run_id("run-1")
    assert [e.node_name for e in executions] == [
        "check_conversation_mode",
        "resolve_interaction",
        "agreement",
    ]


@pytest.mark.asyncio
async def test_compiled_graph_persists_state_via_checkpointer_by_thread_id():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-checkpoint-1", mode="agent"))
    checkpointer = MemorySaver()
    compiled = _compile(conversation_repository=conversation_repository, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "conv-checkpoint-1"}}

    await compiled.ainvoke(
        make_agent_state(conversation_id="conv-checkpoint-1", user_message="hola"), config=config
    )
    restored = await compiled.aget_state(config)

    assert restored.values["conversation_id"] == "conv-checkpoint-1"


async def test_state_reset_graph_clears_collected_data_the_real_graph_wrote():
    # This is the follow-up worker's own mechanism, exercised end to end:
    # a completely separate, dependency-free graph resets `collected_data`
    # for a `thread_id` the FULLY-WIRED graph already checkpointed.
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="agent"))
    checkpointer = MemorySaver()
    compiled = _compile(
        conversation_repository=conversation_repository,
        specialty_gateway=make_specialty_gateway(specialties=[make_specialty(id_="cleaning")]),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "conv-1"}}
    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="Quiero un turno"), config=config
    )
    assert result["collected_data"].get("stage") is not None

    reset_graph = build_state_reset_graph(checkpointer)
    await reset_graph.aupdate_state(config, {"collected_data": {}})

    snapshot = await compiled.aget_state(config)
    assert snapshot.values["collected_data"] == {}
