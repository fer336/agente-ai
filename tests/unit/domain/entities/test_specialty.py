from app.domain.entities.specialty import Specialty


def test_creates_specialty_with_all_fields():
    specialty = Specialty(id="spec-1", name="Ortodoncia")

    assert specialty.id == "spec-1"
    assert specialty.name == "Ortodoncia"


def test_specialties_with_different_name_are_not_equal():
    first = Specialty(id="spec-2", name="Ortodoncia")
    second = Specialty(id="spec-2", name="Endodoncia")

    assert first != second
