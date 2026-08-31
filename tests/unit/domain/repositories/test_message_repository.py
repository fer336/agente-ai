from app.domain.repositories.message_repository import MessageRepository


class ConformingMessageRepository:
    async def exists_by_external_id(self, external_message_id):
        return False

    async def save(self, message):
        return None

    async def get_by_id(self, message_id):
        return None

    async def update(self, message):
        return None

    async def get_by_conversation_id(self, conversation_id):
        return []


class PartialMessageRepository:
    async def exists_by_external_id(self, external_message_id):
        return False


def test_conforming_class_satisfies_message_repository_protocol():
    assert isinstance(ConformingMessageRepository(), MessageRepository)


def test_partial_class_does_not_satisfy_message_repository_protocol():
    assert not isinstance(PartialMessageRepository(), MessageRepository)
