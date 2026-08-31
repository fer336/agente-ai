import pytest
from fastapi import HTTPException

from app.api.dependencies.internal_eval import (
    get_evaluate_chat_turn_use_case,
    require_internal_eval_enabled,
)
from app.application.admin.evaluate_chat_turn import EvaluateChatTurnUseCase
from app.config.settings import Settings


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
