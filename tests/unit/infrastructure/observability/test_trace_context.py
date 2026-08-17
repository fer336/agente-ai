from app.infrastructure.observability.trace_context import (
    TraceContext,
    get_trace_context,
    use_trace_context,
)
from tests.fixtures.gateways import make_error_service, make_tool_execution_repository


def test_get_trace_context_returns_none_outside_a_context():
    assert get_trace_context() is None


def test_use_trace_context_makes_it_available_inside_the_block():
    context = TraceContext(
        agent_run_id="run-1",
        node_execution_id="ne-1",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
    )

    with use_trace_context(context):
        assert get_trace_context() is context

    assert get_trace_context() is None


def test_use_trace_context_restores_the_previous_context_on_nested_use():
    outer = TraceContext(
        agent_run_id="run-outer",
        node_execution_id="ne-outer",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
    )
    inner = TraceContext(
        agent_run_id="run-inner",
        node_execution_id="ne-inner",
        tool_execution_repository=make_tool_execution_repository(),
        error_service=make_error_service(),
    )

    with use_trace_context(outer):
        with use_trace_context(inner):
            assert get_trace_context() is inner
        assert get_trace_context() is outer
