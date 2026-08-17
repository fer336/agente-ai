from datetime import datetime

from app.domain.entities.scheduled_action import ScheduledAction


class FakeScheduledActionRepository:
    """In-memory fake implementing `ScheduledActionRepository` for local dev and tests."""

    def __init__(self) -> None:
        self._by_id: dict[str, ScheduledAction] = {}

    async def get_by_id(self, scheduled_action_id: str) -> ScheduledAction | None:
        return self._by_id.get(scheduled_action_id)

    async def save(self, scheduled_action: ScheduledAction) -> None:
        self._by_id[scheduled_action.id] = scheduled_action

    async def get_due(self, now: datetime, limit: int) -> list[ScheduledAction]:
        due = [
            scheduled_action
            for scheduled_action in self._by_id.values()
            if scheduled_action.status == "scheduled" and scheduled_action.scheduled_for <= now
        ]
        due.sort(key=lambda scheduled_action: scheduled_action.scheduled_for)
        return due[:limit]

    async def get_by_pending_action_id(self, pending_action_id: str) -> ScheduledAction | None:
        for scheduled_action in self._by_id.values():
            if scheduled_action.pending_action_id == pending_action_id:
                return scheduled_action
        return None

    async def transition_status(
        self, scheduled_action_id: str, *, from_status: str, to_status: str
    ) -> bool:
        scheduled_action = self._by_id.get(scheduled_action_id)
        if scheduled_action is None or scheduled_action.status != from_status:
            return False
        scheduled_action.status = to_status
        return True
