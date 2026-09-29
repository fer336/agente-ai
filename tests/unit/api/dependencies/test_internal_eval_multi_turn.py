"""A multi-turn eval conversation must keep its state between HTTP requests.

Regression guard for the promptfoo multi-turn flows: the provider used to build a
brand-new isolated stack (repositories, checkpointer, patient/appointment fakes) on
every request, so turn 2 never saw turn 1.
"""

from datetime import UTC, datetime

import pytest

from app.api.dependencies import internal_eval
from app.domain.value_objects.conversation_id import ConversationId
from tests.fixtures.fake_redis import InMemoryFakeRedis

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _in_memory_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = InMemoryFakeRedis()
    monkeypatch.setattr(internal_eval, "get_shared_redis_client", lambda: redis)


@pytest.mark.asyncio
async def test_a_button_tap_on_turn_two_continues_the_conversation_of_turn_one():
    provider = internal_eval.get_eval_use_case_provider()
    conversation_id = ConversationId("eval-multi-turn-regression")

    first = await provider(conversation_id).execute(
        conversation_id, "Agendar una cita", now=_NOW, button_payload="OPERATION_CREATE"
    )
    second = await provider(conversation_id).execute(
        conversation_id, "✅ Confirmar", now=_NOW, button_payload="FIRST_VISIT_CONFIRM"
    )

    assert first.reply_kind == "buttons"
    assert [b.id for b in first.buttons] == ["FIRST_VISIT_CONFIRM", "FIRST_VISIT_CANCEL"]
    assert second.reply_text is not None
    assert "- DNI" in second.reply_text
