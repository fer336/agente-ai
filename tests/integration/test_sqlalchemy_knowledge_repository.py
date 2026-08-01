from app.infrastructure.database.models.approved_content import ApprovedContentModel
from app.infrastructure.database.repositories.knowledge_repository import (
    SqlAlchemyKnowledgeRepository,
)


async def test_search_filters_by_category_and_keywords(db_session):
    db_session.add_all(
        [
            ApprovedContentModel(
                id="content-1",
                category="opening_hours",
                title="Horario",
                body="Lunes a viernes de 9 a 18",
                keywords=["horario", "atencion"],
            ),
            ApprovedContentModel(
                id="content-2",
                category="faq",
                title="Pagos",
                body="Aceptamos efectivo y tarjeta",
                keywords=["pago", "tarjeta"],
            ),
        ]
    )
    await db_session.flush()

    repository = SqlAlchemyKnowledgeRepository(db_session)

    by_category = await repository.search(category="faq", keywords=[])
    assert [content.id for content in by_category] == ["content-2"]

    by_keyword = await repository.search(category=None, keywords=["horario"])
    assert [content.id for content in by_keyword] == ["content-1"]
