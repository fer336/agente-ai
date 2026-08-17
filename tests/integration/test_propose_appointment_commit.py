"""Proves `open_sqlalchemy_proposal_repositories` durably commits (PRD.md §16.2).

Unlike the `db_session`-fixture-scoped repository round-trip tests
elsewhere (which only prove same-session read-your-writes), this uses the
REAL production provider (`app.api.dependencies.db._get_session_factory`,
via `ProposeAppointmentUseCase`) and then reads back through a SEPARATE,
freshly-opened session — proving the write is actually durable, not just
visible within the same still-open transaction.
"""

from app.api.dependencies.db import _get_session_factory
from app.api.dependencies.repositories import open_sqlalchemy_proposal_repositories
from app.application.appointments.propose_appointment import ProposeAppointmentUseCase
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.repositories.outbox_repository import SqlAlchemyOutboxRepository
from app.infrastructure.database.repositories.pending_action_repository import (
    SqlAlchemyPendingActionRepository,
)
from app.infrastructure.database.repositories.scheduled_action_repository import (
    SqlAlchemyScheduledActionRepository,
)


async def test_propose_appointment_is_durably_committed_and_visible_from_a_fresh_session(
    db_session, conversation_id
):
    # `db_session` only sets up/tears down the schema here — the actual
    # write under test goes through the REAL provider, a different
    # session/engine pointed at the same database.
    use_case = ProposeAppointmentUseCase(
        repositories_provider=open_sqlalchemy_proposal_repositories,
        confirmation_timeout_seconds=120,
    )

    pending_action = await use_case.execute(
        ConversationId(conversation_id), "create_appointment", {"slot_id": "slot-1"}
    )

    session_factory = _get_session_factory()
    async with session_factory() as fresh_session:
        pending_action_repository = SqlAlchemyPendingActionRepository(fresh_session)
        scheduled_action_repository = SqlAlchemyScheduledActionRepository(fresh_session)
        outbox_repository = SqlAlchemyOutboxRepository(fresh_session)

        fetched_pending_action = await pending_action_repository.get_by_id(pending_action.id)
        assert fetched_pending_action is not None
        assert fetched_pending_action.status == "pending"

        due = await scheduled_action_repository.get_due(pending_action.expires_at, limit=50)
        matching_scheduled = [sa for sa in due if sa.pending_action_id == pending_action.id]
        assert len(matching_scheduled) == 1

        pending_events = await outbox_repository.fetch_pending(limit=50)
        matching_events = [e for e in pending_events if e.aggregate_id == pending_action.id]
        assert len(matching_events) == 1
