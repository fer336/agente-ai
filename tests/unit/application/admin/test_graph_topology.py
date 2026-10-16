from unittest.mock import MagicMock

from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.first_visit_intake_subgraph import build_first_visit_intake_graph
from app.agent.graph import HANDLE_ERROR_NODE, build_graph
from app.application.admin.graph_topology import GraphView, get_graph_topology


def _by_id() -> dict[str, GraphView]:
    return {graph.id: graph for graph in get_graph_topology()}


def test_exposes_the_three_graphs_with_spanish_labels_and_excludes_noop():
    graphs = get_graph_topology()

    assert [(g.id, g.label) for g in graphs] == [
        ("main", "Principal"),
        ("appointment_decision", "Decisión de turno"),
        ("first_visit_intake", "Primera visita"),
    ]
    for graph in graphs:
        assert "noop" not in {node.id for node in graph.nodes}


def test_main_graph_contains_the_nodes_the_stale_diagram_was_missing():
    node_ids = {node.id for node in _by_id()["main"].nodes}

    assert {"faq_topic", "payment_admin", "reminder_action"} <= node_ids


def test_every_edge_endpoint_is_a_declared_node_and_each_graph_has_start_and_end():
    for graph in get_graph_topology():
        node_ids = {node.id for node in graph.nodes}
        kinds = {node.kind for node in graph.nodes}
        assert {"start", "end"} <= kinds
        for edge in graph.edges:
            assert edge.source in node_ids, (graph.id, edge)
            assert edge.target in node_ids, (graph.id, edge)


def test_only_error_handled_main_graph_nodes_are_traced():
    graphs = _by_id()
    main_nodes = {node.id: node for node in graphs["main"].nodes}

    traced = {node_id for node_id, node in main_nodes.items() if node.traced}
    assert len(traced) == 13
    assert HANDLE_ERROR_NODE not in traced
    assert all(not main_nodes[i].traced for i, n in main_nodes.items() if n.kind != "node")
    for graph_id in ("appointment_decision", "first_visit_intake"):
        assert not any(node.traced for node in graphs[graph_id].nodes)


def test_conditional_flag_is_preserved():
    edges = {(e.source, e.target): e.conditional for e in _by_id()["main"].edges}

    assert edges[("__start__", "check_conversation_mode")] is False
    assert edges[("resolve_interaction", "faq_topic")] is True


def _topology_of(compiled) -> tuple[set[str], set[tuple[str, str, bool]]]:
    drawable = compiled.get_graph()
    return (
        set(drawable.nodes),
        {(e.source, e.target, e.conditional) for e in drawable.edges},
    )


def test_drift_guard_matches_graphs_built_the_way_existing_tests_build_them():
    mock = MagicMock()
    main = build_graph(
        mock, mock, mock, mock, mock, mock, mock, mock, mock, 1, mock, "run-1", mock, mock
    ).compile()
    decision = build_appointment_decision_graph(
        appointment_gateway=mock,
        specialty_gateway=mock,
        conversation_repository=mock,
        llm_provider=mock,
    )
    intake = build_first_visit_intake_graph()
    expected = {
        "main": _topology_of(main),
        "appointment_decision": _topology_of(decision),
        "first_visit_intake": _topology_of(intake),
    }

    for graph in get_graph_topology():
        assert (
            {node.id for node in graph.nodes},
            {(e.source, e.target, e.conditional) for e in graph.edges},
        ) == expected[graph.id]
