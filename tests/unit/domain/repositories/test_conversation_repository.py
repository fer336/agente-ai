from app.domain.repositories.conversation_repository import ConversationRepository


class ConformingConversationRepository:
    async def get_by_id(self, conversation_id):
        return None

    async def save(self, conversation):
        return None


class PartialConversationRepository:
    async def get_by_id(self, conversation_id):
        return None


def test_conforming_class_satisfies_conversation_repository_protocol():
    assert isinstance(ConformingConversationRepository(), ConversationRepository)


def test_partial_class_does_not_satisfy_conversation_repository_protocol():
    assert not isinstance(PartialConversationRepository(), ConversationRepository)
