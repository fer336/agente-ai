from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class RuntimeAgentConfigModel(Base):
    """Row shape for the `runtime_agent_config` table — one row, holding
    the admin-editable model/temperature/debounce/prompts.
    """

    __tablename__ = "runtime_agent_config"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    debounce_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    classify_intent_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    extract_information_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generate_response_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by: Mapped[str] = mapped_column(String, nullable=False)
    agent_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    paused_by: Mapped[str | None] = mapped_column(String, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contact_filter_mode: Mapped[str] = mapped_column(
        String, nullable=False, server_default="off", default="off"
    )
    contact_filter_phones: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
