from app.domain.repositories.knowledge_repository import KnowledgeRepository


class ConformingKnowledgeRepository:
    async def search(self, category, keywords):
        return []


class NonConformingKnowledgeRepository:
    async def other_method(self):
        pass


def test_conforming_class_satisfies_knowledge_repository_protocol():
    assert isinstance(ConformingKnowledgeRepository(), KnowledgeRepository)


def test_class_missing_search_does_not_satisfy_knowledge_repository_protocol():
    assert not isinstance(NonConformingKnowledgeRepository(), KnowledgeRepository)
