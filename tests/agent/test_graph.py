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
    build_graph,
    compile_graph,
)
from app.domain.value_objects.conversation_id import ConversationId
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
    make_tool_execution_repository,
)
from tests.fixtures.seed_objects import make_agreement, make_conversation


def _build_graph(conversation_repository=None):
    return build_graph(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=FakeAgreementGateway(),
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
    conversation_repository=None, agreement_gateway=None, checkpointer=None, error_service=None
):
    return compile_graph(
        appointment_gateway=FakeDentalinkGateway(),
        agreement_gateway=agreement_gateway or FakeAgreementGateway(),
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

    assert "Turnos" in result["response_text"]


@pytest.mark.asyncio
async def test_human_mode_conversation_ends_the_run_silently():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(make_conversation(id_="conv-1", mode="human"))
    compiled = _compile(conversation_repository=conversation_repository)

    result = await compiled.ainvoke(
        make_agent_state(conversation_id="conv-1", user_message="hola")
    )

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
