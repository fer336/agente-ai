from dataclasses import replace

from app.domain.entities.pending_action import PendingAction
from app.domain.exceptions.errors import InvalidConfirmationError, PendingActionExpiredError
from app.domain.repositories.pending_action_repository import PendingActionRepository

#: PRD.md §16's documented `pending_actions.status` enum.
CANCELLED = "cancelled"


class RejectPendingActionUseCase:
    """Rejects a `PendingAction` at the patient's explicit request (PRD.md §15).

    Unlike `ConfirmPendingActionUseCase`, this does not need a `WHERE status
    = 'pending'`-guarded atomic transition: PRD.md §16.3 only calls out a
    confirm-vs-expire race, never a reject-vs-expire one — the not-yet-built
    expiry worker is the only other writer of this row, and it is out of
    scope for this change (see this change's report). A plain
    read-then-write is enough here; if the action is no longer `pending` by
    the time this runs, that is surfaced instead of silently overwritten.
    """

    def __init__(self, pending_action_repository: PendingActionRepository) -> None:
        self._pending_action_repository = pending_action_repository

    async def execute(self, pending_action_id: str) -> PendingAction:
        pending_action = await self._pending_action_repository.get_by_id(pending_action_id)
        if pending_action is None:
            raise InvalidConfirmationError(pending_action_id)
        if pending_action.status != "pending":
            raise PendingActionExpiredError(pending_action_id)

        rejected = replace(pending_action, status=CANCELLED)
        await self._pending_action_repository.save(rejected)
        return rejected
