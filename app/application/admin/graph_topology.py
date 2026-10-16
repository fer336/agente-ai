from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from app.agent.appointment_decision_subgraph import build_appointment_decision_graph
from app.agent.first_visit_intake_subgraph import build_first_visit_intake_graph
from app.agent.graph import HANDLE_ERROR_NODE, build_graph

NodeKind = Literal["start", "end", "node"]

_START_ID = "__start__"
_END_ID = "__end__"

#: Main-graph nodes NOT wrapped by `with_error_handling` (so they never write a
#: `node_executions` row). Every other main-graph node is wrapped.
_UNTRACED_MAIN_NODES = frozenset({HANDLE_ERROR_NODE})


@dataclass(frozen=True)
class NodeView:
    id: str
    label: str
    kind: NodeKind
    traced: bool


@dataclass(frozen=True)
class EdgeView:
    source: str
    target: str
    conditional: bool


@dataclass(frozen=True)
class GraphView:
    id: str
    label: str
    nodes: tuple[NodeView, ...]
    edges: tuple[EdgeView, ...]


def _view(graph_id: str, label: str, compiled: Any, *, traced_nodes: bool) -> GraphView:
    drawable = compiled.get_graph()
    nodes: list[NodeView] = []
    for node_id in drawable.nodes:
        if node_id == _START_ID:
            nodes.append(NodeView(node_id, "Inicio", "start", False))
        elif node_id == _END_ID:
            nodes.append(NodeView(node_id, "Fin", "end", False))
        else:
            traced = traced_nodes and node_id not in _UNTRACED_MAIN_NODES
            nodes.append(NodeView(node_id, node_id, "node", traced))
    edges = tuple(EdgeView(e.source, e.target, bool(e.conditional)) for e in drawable.edges)
    return GraphView(graph_id, label, tuple(nodes), edges)


@lru_cache(maxsize=1)
def get_graph_topology() -> tuple[GraphView, ...]:
    """Topology of the agent graphs, read from the compiled graphs themselves.

    The builders only close over their dependencies at build time (nothing is
    called until a turn runs), so `None` stubs are enough to read the shape;
    the topology can therefore never drift from the real graphs. The
    `noop` state-reset graph is intentionally not included.
    """
    stub: Any = None
    main = build_graph(
        stub, stub, stub, stub, stub, stub, stub, stub, stub, 0, stub, "", stub, stub
    ).compile()
    decision = build_appointment_decision_graph(
        appointment_gateway=stub,
        specialty_gateway=stub,
        conversation_repository=stub,
        llm_provider=stub,
    )
    intake = build_first_visit_intake_graph()
    return (
        _view("main", "Principal", main, traced_nodes=True),
        _view("appointment_decision", "Decisión de turno", decision, traced_nodes=False),
        _view("first_visit_intake", "Primera visita", intake, traced_nodes=False),
    )
