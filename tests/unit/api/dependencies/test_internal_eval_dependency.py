import pytest
from fastapi import HTTPException

from app.api.dependencies.internal_eval import (
    EvalSessionRegistry,
    get_eval_use_case_provider,
    get_evaluate_chat_turn_use_case,
    require_internal_eval_enabled,
)
from app.application.admin.evaluate_chat_turn import EvaluateChatTurnUseCase
from app.config.settings import Settings
from app.domain.value_objects.conversation_id import ConversationId


def test_require_internal_eval_enabled_raises_404_when_disabled():
    settings = Settings(internal_eval_enabled=False)

    with pytest.raises(HTTPException) as exc_info:
        require_internal_eval_enabled(settings)

    assert exc_info.value.status_code == 404


def test_require_internal_eval_enabled_passes_when_enabled():
    settings = Settings(internal_eval_enabled=True)

    assert require_internal_eval_enabled(settings) is None


def test_get_evaluate_chat_turn_use_case_returns_an_evaluate_chat_turn_use_case():
    use_case = get_evaluate_chat_turn_use_case()

    assert isinstance(use_case, EvaluateChatTurnUseCase)


def test_get_evaluate_chat_turn_use_case_returns_a_fresh_instance_per_call():
    first = get_evaluate_chat_turn_use_case()
    second = get_evaluate_chat_turn_use_case()

    assert first is not second


def test_registry_returns_the_same_use_case_for_the_same_conversation():
    registry = EvalSessionRegistry(max_sessions=10)

    first = registry.get_or_create(ConversationId("c1"), object)
    again = registry.get_or_create(ConversationId("c1"), object)
    other = registry.get_or_create(ConversationId("c2"), object)

    assert first is again
    assert first is not other


def test_registry_evicts_the_least_recently_used_conversation_beyond_its_cap():
    registry = EvalSessionRegistry(max_sessions=2)
    first = registry.get_or_create(ConversationId("c1"), object)
    registry.get_or_create(ConversationId("c2"), object)
    registry.get_or_create(ConversationId("c1"), object)  # c1 is now most recent
    registry.get_or_create(ConversationId("c3"), object)  # evicts c2

    assert registry.get_or_create(ConversationId("c1"), object) is first
    assert len(registry) == 2


def test_provider_builds_a_use_case_per_conversation_and_reuses_it_across_turns():
    provider = get_eval_use_case_provider()

    first = provider(ConversationId("eval-provider-reuse"))
    again = provider(ConversationId("eval-provider-reuse"))
    other = provider(ConversationId("eval-provider-other"))

    assert isinstance(first, EvaluateChatTurnUseCase)
    assert first is again
    assert first is not other
