from typing import Protocol, runtime_checkable

from app.domain.entities.runtime_agent_config import RuntimeAgentConfig


@runtime_checkable
class RuntimeConfigRepository(Protocol):
    """Port to durable storage for the single `RuntimeAgentConfig` row."""

    async def get(self) -> RuntimeAgentConfig | None:
        """`None` when no admin has ever saved a config yet — callers fall
        back to Settings-driven defaults (see `RuntimeConfigService`).
        """
        ...

    async def save(self, config: RuntimeAgentConfig) -> None:
        """Upsert semantics — there is at most one row."""
        ...
