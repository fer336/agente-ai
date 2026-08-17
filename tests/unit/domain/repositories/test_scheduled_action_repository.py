from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository


class ConformingScheduledActionRepository:
    async def get_by_id(self, scheduled_action_id):
        return None

    async def save(self, scheduled_action):
        return None

    async def get_due(self, now, limit):
        return []

    async def get_by_pending_action_id(self, pending_action_id):
        return None

    async def transition_status(self, scheduled_action_id, *, from_status, to_status):
        return False


class PartialScheduledActionRepository:
    async def get_by_id(self, scheduled_action_id):
        return None

    async def save(self, scheduled_action):
        return None


def test_conforming_class_satisfies_scheduled_action_repository_protocol():
    assert isinstance(ConformingScheduledActionRepository(), ScheduledActionRepository)


def test_partial_class_does_not_satisfy_scheduled_action_repository_protocol():
    assert not isinstance(PartialScheduledActionRepository(), ScheduledActionRepository)
