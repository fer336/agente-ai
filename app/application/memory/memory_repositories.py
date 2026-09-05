from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from app.domain.repositories.contact_memory_repository import ContactMemoryRepository
from app.domain.repositories.message_repository import MessageRepository


@dataclass(frozen=True)
class MemoryRepositories:
    """Bundles the two repositories `MemoryService` needs for one unit of
    work (conversational-memory module).

    A separate bundle from `AgentRepositories` (conversations/contacts,
    read-only for `LangGraphAgentInvoker`'s own purposes) — this one holds
    actual durable WRITES (an outbound message, a compacted summary), so its
    production provider commits explicitly, unlike
    `open_sqlalchemy_agent_repositories`.
    """

    messages: MessageRepository
    contact_memories: ContactMemoryRepository


# A zero-arg async context manager factory yielding a fresh `MemoryRepositories`
# for one unit of work. Production implementation MUST commit the underlying
# transaction on success (see `app.api.dependencies.repositories.
# open_sqlalchemy_memory_repositories`) — an outbound message or a compacted
# summary written here must survive past this one `handle()`/`compact()` call.
MemoryRepositoriesProvider = Callable[[], AbstractAsyncContextManager[MemoryRepositories]]
