from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities.error_record import ErrorRecord
from app.domain.value_objects.conversation_id import ConversationId


@runtime_checkable
class ErrorRepository(Protocol):
    """Port to durable storage for errors (PRD.md §42)."""

    async def save(self, error: ErrorRecord) -> None: ...

    async def get_by_id(self, error_id: str) -> ErrorRecord | None: ...

    async def list_recent(self, limit: int = 50) -> list[ErrorRecord]:
        """Lists the `limit` most recent errors, newest first (PRD.md §44)."""
        ...

    async def get_by_conversation_id(self, conversation_id: ConversationId) -> list[ErrorRecord]:
        """Lists every error tied to a conversation (PRD.md §44.1/§44.2)."""
        ...

    async def delete_by_conversation_id(self, conversation_id: ConversationId) -> None:
        """Deletes every error tied to a conversation (`ResetConversationUseCase`).

        Must run before deleting this conversation's `agent_runs` —
        `errors.agent_run_id` is a plain FK with no cascade. NOT
        sufficient on its own: `ErrorService.report` is very often called
        with `agent_run_id` set but `conversation_id` left `None` (see its
        call sites), so callers must also call `delete_by_agent_run_id`
        for each of this conversation's runs.
        """
        ...

    async def delete_by_agent_run_id(self, agent_run_id: str) -> None:
        """Deletes every error tied to one run, including one whose
        `conversation_id` was never set (`ResetConversationUseCase`) —
        the common case for an unhandled-node-exception error report (see
        `app.agent.nodes.error_handling.with_error_handling`), which
        `delete_by_conversation_id` alone would miss.
        """
        ...

    async def count_recent(self, source: str, error_type: str, since: datetime) -> int:
        """Counts errors of this `source`+`error_type` since `since`.

        The "aislado" vs "repetido" distinction PRD.md §46's severity
        examples draw (e.g. "dentalink_timeout aislado" = WARNING vs
        "dentalink_timeout repetido" = ERROR) is decided from this count —
        `errors` has no `operation` column (unlike `incidents`, PRD.md
        §49), so this only ever groups by source+error_type.
        """
        ...
