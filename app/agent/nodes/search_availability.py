from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.agent.state import AgentState
from app.application.appointments.search_availability import SearchAvailabilityUseCase
from app.domain.repositories.gateways import AppointmentGateway
from app.domain.value_objects.date_time_range import DateTimeRange

#: Demo search window for the example node — no real business logic (doc §5.2).
_DEFAULT_SEARCH_WINDOW = timedelta(days=30)


class SearchAvailabilityNode(Protocol):
    """Callable shape LangGraph's `StateGraph.add_node` expects.

    Declared as a `Protocol` (rather than `Callable[[AgentState], Awaitable[...]]`)
    because LangGraph's `add_node` overloads are generic over the node's
    `__call__` signature — a plain `Callable[...]` alias does not resolve
    those overloads under mypy strict, while a matching `Protocol` does.
    """

    def __call__(self, state: AgentState) -> Awaitable[dict[str, Any]]: ...


def create_search_availability_node(
    gateway: AppointmentGateway,
) -> SearchAvailabilityNode:
    """Builds the `search_availability` LangGraph node bound to `gateway`.

    Demonstrates the tool → use case → gateway pattern (architecture doc
    §5.2) without real business logic: it searches the next
    `_DEFAULT_SEARCH_WINDOW` with no specialty/professional filter and writes
    the resulting slots into `AgentState.collected_data["available_slots"]`,
    preserving any other keys already present.
    """

    use_case = SearchAvailabilityUseCase(gateway)

    async def node(state: AgentState) -> dict[str, Any]:
        now = datetime.now(UTC)
        slots = await use_case.execute(
            specialty_id=None,
            professional_id=None,
            date_range=DateTimeRange(now, now + _DEFAULT_SEARCH_WINDOW),
        )
        collected_data = {**state["collected_data"], "available_slots": slots}
        return {"collected_data": collected_data}

    return node
