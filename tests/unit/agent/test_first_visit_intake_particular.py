from app.agent.first_visit_intake_subgraph import missing_intake_fields, review_text

_PARTICULAR = {
    "full_name": "Jorgelina Laura Acosta",
    "dni": "38827132",
    "email": "jorgelina@example.com",
    "obra_social": "Particular",
}


def test_a_particular_patient_is_not_asked_for_a_plan():
    # Live case: name, DNI, mail and "Particular" were all given, and the bot still asked
    # for the plan. A particular patient has no insurance, so no plan exists.
    assert missing_intake_fields(_PARTICULAR) == []


def test_particular_is_matched_regardless_of_case_and_spacing():
    assert missing_intake_fields({**_PARTICULAR, "obra_social": "  PARTICULAR "}) == []


def test_an_insured_patient_is_still_asked_for_the_plan():
    assert missing_intake_fields({**_PARTICULAR, "obra_social": "OSDE"}) == ["plan"]


def test_the_review_of_a_particular_patient_has_no_plan_line():
    text = review_text(_PARTICULAR)

    assert "Obra social: Particular" in text
    assert "Plan" not in text
