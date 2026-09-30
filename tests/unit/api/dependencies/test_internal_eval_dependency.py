import pytest
from fastapi import HTTPException

from app.api.dependencies import internal_eval
from app.api.dependencies.internal_eval import (
    EvalSessionRegistry,
    get_eval_use_case_provider,
    get_evaluate_chat_turn_use_case,
    require_internal_eval_enabled,
)
from app.application.admin.evaluate_chat_turn import EvaluateChatTurnUseCase
from app.config.settings import Settings
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider


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


def _llm_of(use_case: EvaluateChatTurnUseCase) -> object:
    return use_case._agent_invoker._llm_provider  # type: ignore[attr-defined]


def test_eval_stack_uses_the_fake_llm_by_default(monkeypatch):
    monkeypatch.setattr(
        internal_eval,
        "get_settings",
        lambda: Settings(internal_eval_real_llm=False, _env_file=None),
    )

    assert isinstance(_llm_of(get_evaluate_chat_turn_use_case()), FakeLLMProvider)


def test_eval_stack_uses_the_webhook_llm_provider_when_the_real_llm_is_opted_in(monkeypatch):
    real_provider = object()
    monkeypatch.setattr(
        internal_eval,
        "get_settings",
        lambda: Settings(
            internal_eval_real_llm=True, llm_api_url="http://llm.invalid/v1", _env_file=None
        ),
    )
    monkeypatch.setattr(internal_eval, "get_llm_provider", lambda: real_provider)

    assert _llm_of(get_evaluate_chat_turn_use_case()) is real_provider


def test_real_llm_opt_in_without_an_llm_url_fails_loudly_instead_of_faking(monkeypatch):
    monkeypatch.setattr(
        internal_eval,
        "get_settings",
        lambda: Settings(internal_eval_real_llm=True, llm_api_url="", _env_file=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        get_evaluate_chat_turn_use_case()

    assert exc_info.value.status_code == 503
