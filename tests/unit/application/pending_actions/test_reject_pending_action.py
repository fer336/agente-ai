import pytest

from app.application.pending_actions.reject_pending_action import RejectPendingActionUseCase
from app.domain.exceptions.errors import InvalidConfirmationError, PendingActionExpiredError
from tests.fixtures.gateways import make_pending_action_repository
from tests.fixtures.seed_objects import make_pending_action


@pytest.mark.asyncio
async def test_execute_rejects_a_pending_action():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="pending"))
    use_case = RejectPendingActionUseCase(repository)

    rejected = await use_case.execute("pa-1")

    assert rejected.status == "cancelled"
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "cancelled"


@pytest.mark.asyncio
async def test_execute_preserves_the_rest_of_the_pending_action_fields():
    repository = make_pending_action_repository()
    original = make_pending_action(id_="pa-1", status="pending", payload={"slot_id": "slot-1"})
    await repository.save(original)
    use_case = RejectPendingActionUseCase(repository)

    rejected = await use_case.execute("pa-1")

    assert rejected.id == original.id
    assert rejected.conversation_id == original.conversation_id
    assert rejected.action_type == original.action_type
    assert rejected.payload == original.payload
    assert rejected.confirmation_token == original.confirmation_token
    assert rejected.expires_at == original.expires_at


@pytest.mark.asyncio
async def test_execute_raises_when_pending_action_does_not_exist():
    repository = make_pending_action_repository()
    use_case = RejectPendingActionUseCase(repository)

    with pytest.raises(InvalidConfirmationError) as exc_info:
        await use_case.execute("missing")

    assert exc_info.value.pending_action_id == "missing"


@pytest.mark.asyncio
async def test_execute_raises_expired_when_no_longer_pending():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="expired"))
    use_case = RejectPendingActionUseCase(repository)

    with pytest.raises(PendingActionExpiredError) as exc_info:
        await use_case.execute("pa-1")

    assert exc_info.value.pending_action_id == "pa-1"
