import pytest

from app.application.pending_actions.confirm_pending_action import ConfirmPendingActionUseCase
from app.domain.exceptions.errors import InvalidConfirmationError, PendingActionExpiredError
from tests.fixtures.gateways import make_pending_action_repository
from tests.fixtures.seed_objects import make_pending_action


@pytest.mark.asyncio
async def test_execute_confirms_a_pending_action():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="pending"))
    use_case = ConfirmPendingActionUseCase(repository)

    confirmed = await use_case.execute("pa-1")

    assert confirmed.status == "confirmed"
    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "confirmed"


@pytest.mark.asyncio
async def test_execute_raises_when_pending_action_does_not_exist():
    repository = make_pending_action_repository()
    use_case = ConfirmPendingActionUseCase(repository)

    with pytest.raises(InvalidConfirmationError) as exc_info:
        await use_case.execute("missing")

    assert exc_info.value.pending_action_id == "missing"


@pytest.mark.asyncio
async def test_execute_raises_expired_when_already_expired():
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="expired"))
    use_case = ConfirmPendingActionUseCase(repository)

    with pytest.raises(PendingActionExpiredError) as exc_info:
        await use_case.execute("pa-1")

    assert exc_info.value.pending_action_id == "pa-1"


@pytest.mark.asyncio
async def test_execute_raises_expired_when_already_confirmed_by_a_race_winner():
    # PRD.md §16.3: only one of {confirm, expire} can win — simulate the
    # follow-up worker having already won.
    repository = make_pending_action_repository()
    await repository.save(make_pending_action(id_="pa-1", status="expired"))
    use_case = ConfirmPendingActionUseCase(repository)

    with pytest.raises(PendingActionExpiredError):
        await use_case.execute("pa-1")

    fetched = await repository.get_by_id("pa-1")
    assert fetched is not None
    assert fetched.status == "expired"
