from collections.abc import Awaitable
from typing import Any, Protocol

from app.agent.state import AgentState


class AgentNode(Protocol):
    """Callable shape LangGraph's `StateGraph.add_node` expects.

    Declared as a `Protocol` (rather than a plain `Callable[...]` alias)
    because LangGraph's `add_node` overloads are generic over the node's
    `__call__` signature — a plain `Callable[...]` alias does not resolve
    those overloads under mypy strict, while a matching `Protocol` does.
    Shared by every node in this package except
    `search_availability.py`'s `SearchAvailabilityNode`, which predates
    this one and stays local to that file.
    """

    def __call__(self, state: AgentState) -> Awaitable[dict[str, Any]]: ...
