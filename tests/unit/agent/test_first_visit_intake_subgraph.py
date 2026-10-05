import pytest

from app.agent.first_visit_intake_subgraph import (
    FIRST_VISIT_CANCEL_PAYLOAD,
    FIRST_VISIT_CONFIRM_PAYLOAD,
    FIRST_VISIT_EXISTING_DNI_NO_PAYLOAD,
    FIRST_VISIT_EXISTING_DNI_YES_PAYLOAD,
    FIRST_VISIT_EXISTING_PATIENT_PAYLOAD,
    FIRST_VISIT_QUESTION,
    FIRST_VISIT_REVIEW_CANCEL_PAYLOAD,
    FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
    FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
    build_first_visit_intake_graph,
    existing_dni_confirmation_turn,
)

_ALL_FIELDS = {
    "full_name": "Ana Pérez",
    "dni": "30123456",
    "email": "ana@example.com",
    "obra_social": "OSDE",
    "plan": "210",
}


def test_static_question_names_both_buttons_and_never_mentions_confirm_or_cancel():
    text = FIRST_VISIT_QUESTION.casefold()

    assert "soy paciente nuevo" in text
    assert "ya soy paciente" in text
    assert "confirm" not in text
    assert "cancel" not in text


@pytest.mark.asyncio
async def test_question_button_titles_fit_the_whatsapp_limit():
    state = await build_first_visit_intake_graph().ainvoke({"stage": "offer", "details": {}})

    assert all(len(b.title) <= 20 for b in state["response_buttons"])


@pytest.mark.asyncio
async def test_offer_asks_the_first_visit_question_with_confirm_and_cancel_buttons():
    state = await build_first_visit_intake_graph().ainvoke({"stage": "offer", "details": {}})

    assert state["stage"] == "question"
    assert state["ask_kind"] == "question"
    assert state.get("ask_fields") is None
    assert [(b.id, b.title) for b in state["response_buttons"]] == [
        (FIRST_VISIT_CONFIRM_PAYLOAD, "Soy paciente nuevo"),
        (FIRST_VISIT_CANCEL_PAYLOAD, "Ya soy paciente"),
    ]
    text = state["response_text"]
    assert "primera" in text.casefold()
    assert "hola" not in text.casefold()
    assert "asistente" not in text.casefold()
    assert "- " not in text
    assert state["next_action"] == "none"


@pytest.mark.asyncio
async def test_confirming_the_question_lists_every_missing_field_in_fixed_order():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "question", "details": {}, "button_payload": FIRST_VISIT_CONFIRM_PAYLOAD}
    )

    assert state["stage"] == "collect"
    assert state["ask_kind"] == "first"
    assert state["ask_fields"] == ["full_name", "dni", "email", "obra_social", "plan"]
    assert state["response_buttons"] is None
    text = state["response_text"]
    assert "hola" not in text.casefold()
    assert "primera" not in text.casefold()
    assert text.endswith("- Nombre completo\n- DNI\n- Correo electrónico\n- Obra social\n- Plan")


@pytest.mark.asyncio
async def test_confirming_skips_fields_already_known():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "question",
            "details": {"full_name": "Ana Pérez", "dni": "30123456"},
            "button_payload": FIRST_VISIT_CONFIRM_PAYLOAD,
        }
    )

    assert state["ask_fields"] == ["email", "obra_social", "plan"]
    assert state["response_text"].endswith("- Correo electrónico\n- Obra social\n- Plan")
    assert "- Nombre completo" not in state["response_text"]
    assert "- DNI" not in state["response_text"]


@pytest.mark.asyncio
async def test_a_first_visit_answer_with_inline_details_only_asks_the_missing_fields():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "question",
            "details": {},
            "first_visit_answer": "new",
            "extracted_details": {"full_name": "Juan Perez", "dni": "30123456"},
        }
    )

    assert state["stage"] == "collect"
    assert state["details"] == {"full_name": "Juan Perez", "dni": "30123456"}
    assert state["ask_fields"] == ["email", "obra_social", "plan"]


@pytest.mark.asyncio
async def test_cancelling_the_question_hands_over_to_identification():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "question", "details": {}, "button_payload": FIRST_VISIT_CANCEL_PAYLOAD}
    )

    assert state["next_action"] == "identify"
    assert state["ready_to_persist"] is False


@pytest.mark.parametrize(
    ("answer", "expected_stage", "expected_action"),
    [("new", "collect", "none"), ("existing", None, "identify")],
)
@pytest.mark.asyncio
async def test_a_free_text_first_visit_answer_behaves_like_the_matching_button(
    answer, expected_stage, expected_action
):
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "question", "details": {}, "first_visit_answer": answer}
    )

    assert state["next_action"] == expected_action
    if expected_stage is not None:
        assert state["stage"] == expected_stage
        assert state["ask_kind"] == "first"


@pytest.mark.asyncio
async def test_an_unclear_answer_asks_the_question_again_with_the_buttons():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "question", "details": {}, "first_visit_answer": None, "user_message": "mmm"}
    )

    assert state["stage"] == "question"
    assert state["ask_kind"] == "question"
    assert [b.id for b in state["response_buttons"]] == [
        FIRST_VISIT_CONFIRM_PAYLOAD,
        FIRST_VISIT_CANCEL_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_a_legacy_checkpoint_in_collect_stays_in_collection():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "collect", "details": {"full_name": "Ana Pérez"}, "extracted_details": {}}
    )

    assert state["stage"] == "collect"
    assert state["ask_fields"] == ["dni", "email", "obra_social", "plan"]


@pytest.mark.asyncio
async def test_partial_reply_re_asks_only_the_missing_fields():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "collect",
            "details": {"full_name": "Ana Pérez", "dni": "30123456"},
            "extracted_details": {"email": "ana@example.com"},
        }
    )

    assert state["stage"] == "collect"
    assert state["details"]["email"] == "ana@example.com"
    assert state["ask_fields"] == ["obra_social", "plan"]
    assert state["response_text"].endswith("- Obra social\n- Plan")
    assert "primera vez" not in state["response_text"].casefold()
    assert state["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_invalid_extracted_value_is_not_stored_and_is_asked_again():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "collect",
            "details": {"full_name": "Ana Pérez", "dni": "30123456"},
            "extracted_details": {"email": "no-es-un-mail", "obra_social": "OSDE"},
        }
    )

    assert "email" not in state["details"]
    assert state["details"]["obra_social"] == "OSDE"
    assert state["ask_fields"] == ["email", "plan"]


@pytest.mark.asyncio
async def test_all_five_fields_go_to_review_with_confirm_modify_cancel():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "collect",
            "details": {"full_name": "Ana Pérez", "dni": "30123456"},
            "extracted_details": {
                "email": "ana@example.com",
                "obra_social": "OSDE",
                "plan": "210",
            },
        }
    )

    assert state["stage"] == "review"
    assert state.get("ask_fields") is None
    for value in _ALL_FIELDS.values():
        assert value in state["response_text"]
    assert [button.id for button in state["response_buttons"]] == [
        FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
        FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
        FIRST_VISIT_REVIEW_CANCEL_PAYLOAD,
    ]


@pytest.mark.asyncio
async def test_stating_an_existing_patient_mid_collection_hands_over_to_identification():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "collect", "details": {}, "first_visit_answer": "existing"}
    )

    assert state["next_action"] == "identify"
    assert state["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_legacy_existing_patient_tap_hands_over_to_identification():
    result = await build_first_visit_intake_graph().ainvoke(
        {"button_payload": FIRST_VISIT_EXISTING_PATIENT_PAYLOAD}
    )

    assert result["next_action"] == "identify"
    assert result["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_review_modification_returns_to_review_before_persistence():
    graph = build_first_visit_intake_graph()
    state = await graph.ainvoke({"stage": "review", "details": dict(_ALL_FIELDS)})
    state = await graph.ainvoke({**state, "button_payload": FIRST_VISIT_REVIEW_MODIFY_PAYLOAD})
    assert state["stage"] == "choose_field"
    state = await graph.ainvoke({**state, "user_message": "correo", "button_payload": None})
    assert state["stage"] == "collect"
    assert state["editing_field"] == "email"
    state = await graph.ainvoke({**state, "user_message": "ana.nueva@example.com"})

    assert state["stage"] == "review"
    assert state["details"]["email"] == "ana.nueva@example.com"
    confirmed = await graph.ainvoke({**state, "button_payload": FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD})
    assert confirmed["next_action"] == "persist"
    assert confirmed["ready_to_persist"] is True


@pytest.mark.asyncio
async def test_editing_a_field_with_an_invalid_value_asks_only_that_field_again():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "collect",
            "details": dict(_ALL_FIELDS),
            "editing_field": "dni",
            "user_message": "abc",
        }
    )

    assert state["stage"] == "collect"
    assert state["ask_fields"] == ["dni"]
    assert state["details"]["dni"] == "30123456"


@pytest.mark.asyncio
async def test_review_cancel_offers_the_menu_buttons():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "review",
            "details": dict(_ALL_FIELDS),
            "button_payload": FIRST_VISIT_REVIEW_CANCEL_PAYLOAD,
        }
    )

    assert state["stage"] == "cancelled"
    assert state["next_action"] == "none"


#: Shape checkpointed by the previous intake schema (phone + merged coverage).
_LEGACY_DETAILS = {
    "full_name": "Ana Pérez",
    "dni": "30123456",
    "phone": "+5491198765432",
    "coverage": "OSDE 210",
}


@pytest.mark.asyncio
async def test_legacy_review_state_goes_back_to_collecting_the_missing_fields():
    state = await build_first_visit_intake_graph().ainvoke(
        {"stage": "review", "details": dict(_LEGACY_DETAILS)}
    )

    assert state["stage"] == "collect"
    assert state["details"] == {"full_name": "Ana Pérez", "dni": "30123456"}
    assert state["ask_fields"] == ["email", "obra_social", "plan"]
    assert state["response_text"].endswith("- Correo electrónico\n- Obra social\n- Plan")
    assert state["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_legacy_review_confirm_tap_never_persists_and_asks_for_the_missing_fields():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "review",
            "details": dict(_LEGACY_DETAILS),
            "button_payload": FIRST_VISIT_REVIEW_CONFIRM_PAYLOAD,
        }
    )

    assert state["next_action"] == "none"
    assert state["ready_to_persist"] is False
    assert state["stage"] == "collect"
    assert state["ask_fields"] == ["email", "obra_social", "plan"]


@pytest.mark.parametrize("legacy_field", ["phone", "coverage"])
@pytest.mark.asyncio
async def test_legacy_editing_field_is_cleared_and_the_missing_fields_are_asked(legacy_field):
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "collect",
            "details": dict(_LEGACY_DETAILS),
            "editing_field": legacy_field,
            "user_message": "  ",
        }
    )

    assert state["stage"] == "collect"
    assert state["editing_field"] is None
    assert state["ask_fields"] == ["email", "obra_social", "plan"]


@pytest.mark.asyncio
async def test_review_state_with_missing_fields_never_reviews_or_persists_on_modify():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "review",
            "details": {"full_name": "Ana Pérez", "dni": "30123456", "coverage": "OSDE"},
            "button_payload": FIRST_VISIT_REVIEW_MODIFY_PAYLOAD,
        }
    )

    assert state["stage"] == "collect"
    assert state["ask_fields"] == ["email", "obra_social", "plan"]


_ON_FILE = {"full_name": "María González", "dni": "30123456"}


def test_existing_dni_confirmation_turn_shows_only_name_and_dni_with_short_buttons():
    turn = existing_dni_confirmation_turn(_ALL_FIELDS, "María González", "30123456")

    assert turn["stage"] == "confirm_existing"
    assert turn["existing_patient"] == _ON_FILE
    text = str(turn["response_text"])
    assert "María González" in text
    assert "30123456" in text
    assert "ana@example.com" not in text
    assert "OSDE" not in text
    buttons = turn["response_buttons"]
    assert [(b.id, b.title) for b in buttons] == [
        (FIRST_VISIT_EXISTING_DNI_YES_PAYLOAD, "Sí, soy yo"),
        (FIRST_VISIT_EXISTING_DNI_NO_PAYLOAD, "No soy yo"),
    ]
    assert all(len(b.title) <= 20 for b in buttons)


@pytest.mark.asyncio
async def test_confirming_the_dni_on_file_asks_to_continue_with_that_patient():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "confirm_existing",
            "details": _ALL_FIELDS,
            "existing_patient": _ON_FILE,
            "button_payload": FIRST_VISIT_EXISTING_DNI_YES_PAYLOAD,
        }
    )

    assert state["next_action"] == "use_existing"
    assert state["ready_to_persist"] is False


@pytest.mark.asyncio
async def test_rejecting_the_dni_on_file_asks_for_the_dni_again():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "confirm_existing",
            "details": _ALL_FIELDS,
            "existing_patient": _ON_FILE,
            "button_payload": FIRST_VISIT_EXISTING_DNI_NO_PAYLOAD,
        }
    )

    assert state["stage"] == "collect"
    assert state["editing_field"] == "dni"
    assert state["next_action"] == "none"
    assert state["response_buttons"] is None
    assert "DNI" in state["response_text"]
    assert "ya está registrado con otros datos" not in state["response_text"]


@pytest.mark.asyncio
async def test_typed_text_during_the_dni_confirmation_shows_it_again():
    state = await build_first_visit_intake_graph().ainvoke(
        {
            "stage": "confirm_existing",
            "details": _ALL_FIELDS,
            "existing_patient": _ON_FILE,
            "user_message": "hola",
            "button_payload": None,
        }
    )

    assert state["stage"] == "confirm_existing"
    assert state["next_action"] == "none"
    assert "María González" in state["response_text"]
    assert len(state["response_buttons"]) == 2
