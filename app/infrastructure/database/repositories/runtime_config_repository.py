from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.runtime_agent_config import RUNTIME_AGENT_CONFIG_ID, RuntimeAgentConfig
from app.infrastructure.database.models.runtime_agent_config import RuntimeAgentConfigModel


class SqlAlchemyRuntimeConfigRepository:
    """`RuntimeConfigRepository` implementation backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> RuntimeAgentConfig | None:
        result = await self._session.execute(
            select(RuntimeAgentConfigModel).where(
                RuntimeAgentConfigModel.id == RUNTIME_AGENT_CONFIG_ID
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, config: RuntimeAgentConfig) -> None:
        result = await self._session.execute(
            select(RuntimeAgentConfigModel).where(
                RuntimeAgentConfigModel.id == RUNTIME_AGENT_CONFIG_ID
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = RuntimeAgentConfigModel(id=RUNTIME_AGENT_CONFIG_ID)
            self._session.add(model)

        model.model = config.model
        model.temperature = config.temperature
        model.debounce_seconds = config.debounce_seconds
        model.classify_intent_prompt = config.classify_intent_prompt
        model.extract_information_prompt = config.extract_information_prompt
        model.generate_response_prompt = config.generate_response_prompt
        model.updated_at = config.updated_at
        model.updated_by = config.updated_by
        await self._session.flush()


def _to_entity(model: RuntimeAgentConfigModel) -> RuntimeAgentConfig:
    return RuntimeAgentConfig(
        id=model.id,
        model=model.model,
        temperature=model.temperature,
        debounce_seconds=model.debounce_seconds,
        classify_intent_prompt=model.classify_intent_prompt,
        extract_information_prompt=model.extract_information_prompt,
        generate_response_prompt=model.generate_response_prompt,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
    )
