from app.domain.entities.approved_content import ApprovedContent


def test_creates_approved_content_with_all_fields():
    content = ApprovedContent(
        id="content-1",
        category="opening_hours",
        title="Horario de atencion",
        body="Atendemos de lunes a viernes de 9 a 18.",
        keywords=["horario", "atencion"],
    )

    assert content.category == "opening_hours"
    assert "horario" in content.keywords


def test_approved_contents_with_different_keywords_are_not_equal():
    first = ApprovedContent(id="content-2", category="faq", title="t", body="b", keywords=["a"])
    second = ApprovedContent(id="content-2", category="faq", title="t", body="b", keywords=["b"])

    assert first != second
