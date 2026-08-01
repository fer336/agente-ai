from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.approved_content import ApprovedContent
from app.infrastructure.database.models.approved_content import ApprovedContentModel


class SqlAlchemyKnowledgeRepository:
    """`KnowledgeRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, category: str | None, keywords: list[str]) -> list[ApprovedContent]:
        query = select(ApprovedContentModel)
        if category is not None:
            query = query.where(ApprovedContentModel.category == category)

        result = await self._session.execute(query)
        contents = [_to_entity(model) for model in result.scalars()]

        if not keywords:
            return contents

        return [
            content
            for content in contents
            if any(keyword in content.keywords for keyword in keywords)
        ]


def _to_entity(model: ApprovedContentModel) -> ApprovedContent:
    return ApprovedContent(
        id=model.id,
        category=model.category,
        title=model.title,
        body=model.body,
        keywords=list(model.keywords),
    )
