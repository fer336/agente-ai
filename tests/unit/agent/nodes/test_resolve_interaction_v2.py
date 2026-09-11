import pytest

from app.agent.nodes.resolve_interaction import (
    MENU_INSURANCE_PAYLOAD,
    MENU_LOCATION_PAYLOAD,
    MENU_SPECIALTIES_PAYLOAD,
    create_resolve_interaction_node,
)
from app.domain.repositories.llm_provider import UnderstandingResult
from app.infrastructure.llm.fake_llm_provider import FakeLLMProvider
from tests.fixtures.agent_state import make_agent_state


@pytest.mark.asyncio
async def test_global_specialties_button_temporarily_interrupts_active_appointment():
    node = create_resolve_interaction_node(FakeLLMProvider())
    state = make_agent_state(
        button_payload=MENU_SPECIALTIES_PAYLOAD,
        collected_data={"stage": "awaiting_slot_selection", "chosen_professional_id": "p1"},
    )

    result = await node(state)

    assert result["intent"] == "specialties"
    assert result["interruption"] == "temporary"
    assert result["resume_node"] == "awaiting_slot_selection"
    assert state["collected_data"]["chosen_professional_id"] == "p1"


@pytest.mark.asyncio
async def test_global_insurance_button_temporarily_interrupts_active_appointment():
    node = create_resolve_interaction_node(FakeLLMProvider())
    result = await node(
        make_agent_state(
            button_payload=MENU_INSURANCE_PAYLOAD,
            collected_data={"stage": "awaiting_professional_selection"},
        )
    )

    assert result["intent"] == "insurance"
    assert result["interruption"] == "temporary"


@pytest.mark.asyncio
async def test_location_button_temporarily_interrupts_active_appointment():
    node = create_resolve_interaction_node(FakeLLMProvider())
    result = await node(
        make_agent_state(
            button_payload=MENU_LOCATION_PAYLOAD,
            collected_data={"stage": "awaiting_slot_selection"},
        )
    )

    assert result["intent"] == "location"
    assert result["resume_node"] == "awaiting_slot_selection"


@pytest.mark.asyncio
async def test_free_text_location_does_not_get_trapped_by_active_stage():
    class ExplodingLLM(FakeLLMProvider):
        async def understand(self, message, context):
            raise AssertionError("location must be resolved before the LLM")

    node = create_resolve_interaction_node(ExplodingLLM())
    result = await node(
        make_agent_state(
            user_message="cómo llegar?",
            collected_data={"stage": "awaiting_identification"},
        )
    )

    assert result["intent"] == "location"
    assert result["interruption"] == "temporary"


@pytest.mark.asyncio
async def test_understand_receives_real_conversation_and_workflow_context():
    captured: dict[str, object] = {}

    class CapturingLLM(FakeLLMProvider):
        async def understand(self, message, context):
            captured.update(context)
            return UnderstandingResult(intent="question", confidence=0.95, answer="respuesta")

    node = create_resolve_interaction_node(CapturingLLM())
    result = await node(
        make_agent_state(
            user_message="una consulta",
            recent_messages=[{"role": "user", "content": "quiero un turno"}],
            contact_memory_summary="Paciente recurrente",
            collected_data={"stage": "awaiting_slot_selection", "chosen_professional_id": "p1"},
        )
    )

    assert captured["recent_messages"] == [{"role": "user", "content": "quiero un turno"}]
    assert captured["contact_memory"] == "Paciente recurrente"
    assert captured["active_flow"] == "appointment"
    assert captured["active_stage"] == "awaiting_slot_selection"
    assert captured["workflow_data"] == {
        "stage": "awaiting_slot_selection",
        "chosen_professional_id": "p1",
    }
    assert result["intent"] == "question"
    assert result["interruption"] == "temporary"


@pytest.mark.asyncio
async def test_location_interruption_from_professional_selection_resumes_the_same_cursor():
    # PR 3 hardening regression: the migrated create-selection subgraph
    # (PR 2) must never see internal node names leak into
    # `active_node`/`resume_node` — a temporary detour from
    # `awaiting_professional_selection` must resume that exact legacy stage
    # string, never e.g. `choose_professional`.
    node = create_resolve_interaction_node(FakeLLMProvider())

    result = await node(
        make_agent_state(
            user_message="cómo llegar?",
            collected_data={
                "stage": "awaiting_professional_selection",
                "chosen_specialty_id": "spec-1",
            },
        )
    )

    assert result["intent"] == "location"
    assert result["interruption"] == "temporary"
    assert result["active_node"] == "awaiting_professional_selection"
    assert result["resume_node"] == "awaiting_professional_selection"
    # No `collected_data` key at all means the caller's checkpoint stays
    # exactly as it was — the professional-selection cursor is untouched.
    assert "collected_data" not in result


@pytest.mark.asyncio
async def test_question_interruption_from_slot_selection_preserves_the_slot_cursor():
    class QuestionLLM(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="question", confidence=0.9, answer="Sí, aceptamos OSDE."
            )

    node = create_resolve_interaction_node(QuestionLLM())

    result = await node(
        make_agent_state(
            user_message="¿aceptan OSDE?",
            collected_data={
                "stage": "awaiting_slot_selection",
                "available_slots": ["slot-placeholder"],
                "professional_names": {"p1": "Dra. Laura Pérez"},
            },
        )
    )

    assert result["intent"] == "question"
    assert result["interruption"] == "temporary"
    assert result["active_node"] == "awaiting_slot_selection"
    assert result["resume_node"] == "awaiting_slot_selection"
    # The question is answered by carrying `pending_answer` alongside the
    # untouched slot cursor — `available_slots` survives exactly as it was,
    # so a subsequent valid `SELECT_SLOT:<id>` still resolves against the
    # same checkpointed availability window.
    assert result["collected_data"]["available_slots"] == ["slot-placeholder"]
    assert result["collected_data"]["stage"] == "awaiting_slot_selection"


@pytest.mark.asyncio
async def test_navigation_request_is_carried_to_appointment_without_resetting_identity():
    class NavigatingLLM(FakeLLMProvider):
        async def understand(self, message, context):
            return UnderstandingResult(
                intent="appointment",
                confidence=0.98,
                navigation_target="professional",
            )

    node = create_resolve_interaction_node(NavigatingLLM())
    result = await node(
        make_agent_state(
            user_message="quiero cambiar de profesional",
            collected_data={
                "stage": "awaiting_slot_selection",
                "patient": {"id": "patient-1"},
                "chosen_specialty_id": "s1",
                "chosen_professional_id": "p1",
            },
        )
    )

    assert result["intent"] == "appointment"
    assert result["interruption"] == "navigation"
    assert result["collected_data"]["navigation_target"] == "professional"
    assert result["collected_data"]["patient"] == {"id": "patient-1"}
