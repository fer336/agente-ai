from app.domain.entities.pending_action import PendingAction
from app.domain.exceptions.errors import InvalidConfirmationError, PendingActionExpiredError
from app.domain.repositories.pending_action_repository import PendingActionRepository


class ConfirmPendingActionUseCase:
    """Confirms a `PendingAction`, guarding against a same-moment expiration race (PRD.md §16.3).

    Uses `PendingActionRepository.mark_confirmed_if_pending` — a `WHERE
    status = 'pending'`-guarded atomic transition, symmetric to
    `mark_expired_if_pending` (the follow-up worker's side of the exact
    same race, PRD.md §16.1: "Si una confirmación y el vencimiento ocurren
    simultáneamente, solamente una transición podrá ganar"). Generic, not
    appointment-specific — the caller decides what `action_type`/`payload`
    mean and what to execute once confirmed.
    """

    def __init__(self, pending_action_repository: PendingActionRepository) -> None:
        self._pending_action_repository = pending_action_repository

    async def execute(self, pending_action_id: str) -> PendingAction:
        pending_action = await self._pending_action_repository.get_by_id(pending_action_id)
        if pending_action is None:
            raise InvalidConfirmationError(pending_action_id)

        won = await self._pending_action_repository.mark_confirmed_if_pending(pending_action_id)
        if not won:
            raise PendingActionExpiredError(pending_action_id)

        confirmed = await self._pending_action_repository.get_by_id(pending_action_id)
        if confirmed is None:  # pragma: no cover - impossible: we just confirmed it
            raise InvalidConfirmationError(pending_action_id)
        return confirmed
