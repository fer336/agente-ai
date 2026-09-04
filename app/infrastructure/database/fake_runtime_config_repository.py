from app.domain.entities.runtime_agent_config import RuntimeAgentConfig


class FakeRuntimeConfigRepository:
    """In-memory fake implementing `RuntimeConfigRepository` for local dev and tests."""

    def __init__(self, config: RuntimeAgentConfig | None = None) -> None:
        self._config = config

    async def get(self) -> RuntimeAgentConfig | None:
        return self._config

    async def save(self, config: RuntimeAgentConfig) -> None:
        self._config = config
