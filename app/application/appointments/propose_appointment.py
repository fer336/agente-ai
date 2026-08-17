from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.entities.outbox_event import OutboxEvent
from app.domain.entities.pending_action import PendingAction
from app.domain.entities.scheduled_action import ScheduledAction
from app.domain.repositories.outbox_repository import OutboxRepository
from app.domain.repositories.pending_action_repository import PendingActionRepository
from app.domain.repositories.scheduled_action_repository import ScheduledActionRepository
from app.domain.value_objects.confirmation_token import ConfirmationToken
from app.domain.value_objects.conversation_id import ConversationId
from app.domain.value_objects.idempotency_key import IdempotencyKey

#: PRD.md §16.1's suggested initial confirmation-window duration.
DEFAULT_CONFIRMATION_TIMEOUT_SECONDS = 120

#: PRD.md §16.2's initial `ScheduledAction.action_type`.
APPOINTMENT_CONFIRMATION_TIMEOUT = "appointment_confirmation_timeout"


@dataclass(frozen=True)
class ProposalRepositories:
    """Bundles the three repositories one `ProposeAppointmentUseCase` unit of work needs."""

    pending_actions: PendingActionRepository
    scheduled_actions: ScheduledActionRepository
    outbox: OutboxRepository


# A zero-arg async context manager factory yielding a fresh `ProposalRepositories`
# for one unit of work — same shape as `IngestMessageUseCase`'s own
# `RepositoriesProvider`, but this one's production implementation MUST
# commit the underlying transaction on success (see
# `app.api.dependencies.repositories.open_sqlalchemy_proposal_repositories`).
ProposalRepositoriesProvider = Callable[[], AbstractAsyncContextManager[ProposalRepositories]]


class ProposeAppointmentUseCase:
    """Creates a `PendingAction` + `ScheduledAction` + initial outbox event
    in ONE transaction (PRD.md §16.1-16.2).

    A `PendingAction` is a proposal awaiting confirmation, never a
    reservation (PRD.md §16.1: "PendingAction = propuesta / Turno
    Dentalink = reserva real") — this use case never touches
    `AppointmentGateway`. `action_type`/`payload` are caller-supplied
    rather than appointment-specific here, so the same use case already
    works for reschedule/cancel proposals once those flows exist (PRD.md
    §16 covers all three under the same `pending_actions` model) — the
    caller decides what goes in `payload` and how to interpret it later.

    `repositories_provider` MUST commit the underlying transaction on
    success. This differs from `IngestMessageUseCase`'s and
    `LangGraphAgentInvoker`'s own `repositories_provider`s, which never
    call `.commit()` — a pre-existing gap in this codebase (their writes
    are only ever visible within the same still-open session/transaction,
    never durably committed) that this change does NOT fix everywhere,
    only for this specific transaction, where "all three rows exist
    together or none do" is an explicit PRD requirement. See this change's
    report.
    """

    def __init__(
        self,
        repositories_provider: ProposalRepositoriesProvider,
        confirmation_timeout_seconds: int = DEFAULT_CONFIRMATION_TIMEOUT_SECONDS,
    ) -> None:
        self._repositories_provider = repositories_provider
        self._confirmation_timeout_seconds = confirmation_timeout_seconds

    async def execute(
        self,
        conversation_id: ConversationId,
        action_type: str,
        payload: dict[str, object],
    ) -> PendingAction:
        expires_at = datetime.now(UTC) + timedelta(seconds=self._confirmation_timeout_seconds)
        pending_action = PendingAction(
            id=str(uuid4()),
            conversation_id=conversation_id,
            action_type=action_type,
            payload=payload,
            confirmation_token=ConfirmationToken(value=str(uuid4())),
            status="pending",
            expires_at=expires_at,
        )
        scheduled_action = ScheduledAction(
            id=str(uuid4()),
            conversation_id=conversation_id,
            pending_action_id=pending_action.id,
            action_type=APPOINTMENT_CONFIRMATION_TIMEOUT,
            status="scheduled",
            scheduled_for=expires_at,
            idempotency_key=IdempotencyKey(value=f"expire:{pending_action.id}"),
            attempts=0,
        )
        outbox_event = OutboxEvent(
            id=str(uuid4()),
            event_type="appointment.proposed",
            aggregate_type="pending_action",
            aggregate_id=pending_action.id,
            payload={"conversation_id": str(conversation_id), "action_type": action_type},
            status="pending",
            attempts=0,
        )

        async with self._repositories_provider() as repositories:
            await repositories.pending_actions.save(pending_action)
            await repositories.scheduled_actions.save(scheduled_action)
            await repositories.outbox.save(outbox_event)

        return pending_action
