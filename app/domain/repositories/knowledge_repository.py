from typing import Protocol, runtime_checkable

from app.domain.entities.approved_content import ApprovedContent


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Port to the clinic's structured knowledge base."""

    async def search(self, category: str | None, keywords: list[str]) -> list[ApprovedContent]: ...
