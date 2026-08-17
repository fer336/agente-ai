from app.domain.repositories.pending_action_repository import PendingActionRepository


class ConformingPendingActionRepository:
    async def get_by_id(self, pending_action_id):
        return None

    async def save(self, pending_action):
        return None

    async def get_pending_for_conversation(self, conversation_id):
        return []

    async def mark_expired_if_pending(self, pending_action_id):
        return False

    async def mark_confirmed_if_pending(self, pending_action_id):
        return False


class PartialPendingActionRepository:
    async def get_by_id(self, pending_action_id):
        return None

    async def save(self, pending_action):
        return None


def test_conforming_class_satisfies_pending_action_repository_protocol():
    assert isinstance(ConformingPendingActionRepository(), PendingActionRepository)


def test_partial_class_does_not_satisfy_pending_action_repository_protocol():
    assert not isinstance(PartialPendingActionRepository(), PendingActionRepository)
