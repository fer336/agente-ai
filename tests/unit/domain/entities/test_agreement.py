from app.domain.entities.agreement import Agreement


def test_creates_agreement_with_all_fields():
    agreement = Agreement(id="agr-1", name="OSDE")

    assert agreement.id == "agr-1"
    assert agreement.name == "OSDE"


def test_agreements_with_different_name_are_not_equal():
    first = Agreement(id="agr-2", name="OSDE")
    second = Agreement(id="agr-2", name="Swiss Medical")

    assert first != second
