from app.domain.entities.professional import Professional


def test_creates_professional_with_all_fields():
    professional = Professional(id="prof-1", full_name="Dra. Laura Pérez", specialty_id="cleaning")

    assert professional.id == "prof-1"
    assert professional.full_name == "Dra. Laura Pérez"
    assert professional.specialty_id == "cleaning"


def test_professional_specialty_id_can_be_none():
    professional = Professional(id="prof-2", full_name="Dr. John Roe", specialty_id=None)

    assert professional.specialty_id is None


def test_professionals_with_different_specialty_are_not_equal():
    first = Professional(id="prof-3", full_name="Dra. A", specialty_id="cleaning")
    second = Professional(id="prof-3", full_name="Dra. A", specialty_id="whitening")

    assert first != second
