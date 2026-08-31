"""Integration test for `get_evaluate_chat_turn_use_case`'s real DI wiring
(PRD.md §61) against a real Redis instance — needed because
`LangGraphAgentInvoker` uses Redis for its per-conversation lock during a
real turn, and this codebase (see `tests/integration/test_redis_debounce_lock.py`)
has no production Fake Redis client, only the real one.

Everything else this wiring touches (Dentalink/YCloud/LLM gateways, the
LangGraph checkpointer, every repository) is either a Fake or an in-process
`MemorySaver` — no Postgres needed here, only Redis.

Skips when Redis is unreachable, mirroring `_redis_reachable()` in
`tests/integration/test_redis_debounce_lock.py`.
"""

import socket
from datetime import UTC, datetime

import pytest

from app.api.dependencies.internal_eval import get_evaluate_chat_turn_use_case
from app.config.settings import get_settings
from app.domain.value_objects.conversation_id import ConversationId


def _redis_reachable() -> bool:
    settings = get_settings()
    try:
        with socket.create_connection((settings.redis_host, settings.redis_port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _skip_without_redis() -> None:
    if not _redis_reachable():
        pytest.skip("Redis not reachable for internal-eval wiring integration test")


async def test_get_evaluate_chat_turn_use_case_wires_a_working_isolated_agent():
    """Only asserts a turn completes and produces a trace + a reply, not any
    specific wording (PRD.md §61's own example asserts on tool/behavior
    shape, not copy) — exact conversational content is Promptfoo's job to
    grade once real datasets run against this endpoint.
    """
    use_case = get_evaluate_chat_turn_use_case()

    result = await use_case.execute(
        ConversationId("eval-wiring-check"), "Hola", now=datetime.now(UTC)
    )

    assert result.reply_text is not None
    assert result.agent_run is not None
