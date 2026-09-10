from datetime import UTC, datetime

import pytest

from app.application.conversations.handle_smb_message_echo import HandleSmbMessageEchoUseCase
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.conversation_id import ConversationId
from app.infrastructure.database.fake_conversation_repository import FakeConversationRepository
from tests.fixtures.seed_objects import make_conversation


@pytest.mark.asyncio
async def test_reactivation_command_flips_mode_and_resets_input_state():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="human", input_state="HUMAN")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****4455", is_reactivation_command=True)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"


@pytest.mark.asyncio
async def test_any_human_reply_resets_last_human_reply_at_while_in_human_mode():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="human")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    before = datetime.now(UTC)
    await use_case.execute("+549****4455", is_reactivation_command=False)
    after = datetime.now(UTC)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "human"
    assert conversation.last_human_reply_at is not None
    assert before <= conversation.last_human_reply_at <= after


@pytest.mark.asyncio
async def test_reactivation_command_also_resets_last_human_reply_at_when_still_human():
    # Both effects fire from the same event — the "/bot" command and the
    # timer reset are independent, not mutually exclusive branches.
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="human")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****4455", is_reactivation_command=True)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.last_human_reply_at is not None


@pytest.mark.asyncio
async def test_reactivation_command_rotates_workflow_session_and_marks_fresh_restart():
    # "/bot" must not just flip the mode: the agent must START FRESH on its
    # next turn — old workflow state (stage/collected_data) dies with the
    # rotated generation, and the next graph turn renders the canonical
    # welcome menu deterministically instead of LLM-continuing the old
    # thread. Durable messages/ContactMemory are never touched.
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="human", input_state="HUMAN")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****4455", is_reactivation_command=True)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.input_state == "FREE_INPUT"
    assert conversation.workflow_session_generation == 2
    assert conversation.awaiting_fresh_restart is True


@pytest.mark.asyncio
async def test_reactivation_command_without_rotation_does_not_mark_fresh_restart():
    # A rotation CAS failure (a concurrent turn already rotated) must NOT
    # stamp `awaiting_fresh_restart` either — that turn already consumed
    # the rotation.
    conversation_repository = FakeConversationRepository()
    conversation = make_conversation(id_="ycloud-+549****4455", mode="human")
    conversation.workflow_session_generation = 7
    await conversation_repository.save(conversation)

    class _ContendedRepository(FakeConversationRepository):
        def __init__(self, base: FakeConversationRepository) -> None:
            super().__init__()
            self._base = base

        async def get_by_id(self, conversation_id: ConversationId) -> Conversation | None:
            return await self._base.get_by_id(conversation_id)

        async def save(self, conversation: Conversation) -> None:
            await self._base.save(conversation)

        async def rotate_workflow_session(
            self, conversation_id: ConversationId, expected_generation: int
        ) -> bool:
            return False

    use_case = HandleSmbMessageEchoUseCase(_ContendedRepository(conversation_repository))
    await use_case.execute("+549****4455", is_reactivation_command=True)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "agent"
    assert conversation.awaiting_fresh_restart is False


@pytest.mark.asyncio
async def test_plain_human_reply_does_not_rotate_or_mark_fresh_restart():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="human")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****4455", is_reactivation_command=False)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.mode == "human"
    assert conversation.workflow_session_generation == 1
    assert conversation.awaiting_fresh_restart is False


@pytest.mark.asyncio
async def test_plain_reply_does_not_touch_last_human_reply_at_when_already_agent_mode():
    conversation_repository = FakeConversationRepository()
    await conversation_repository.save(
        make_conversation(id_="ycloud-+549****4455", mode="agent")
    )
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****4455", is_reactivation_command=False)

    conversation = await conversation_repository.get_by_id(ConversationId("ycloud-+549****4455"))
    assert conversation is not None
    assert conversation.last_human_reply_at is None


@pytest.mark.asyncio
async def test_no_ops_when_no_conversation_exists_for_the_phone():
    conversation_repository = FakeConversationRepository()
    use_case = HandleSmbMessageEchoUseCase(conversation_repository)

    await use_case.execute("+549****9999", is_reactivation_command=True)

    assert await conversation_repository.get_by_id(ConversationId("ycloud-+549****9999")) is None
