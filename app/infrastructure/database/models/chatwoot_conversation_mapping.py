from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.models.base import Base


class ChatwootConversationMappingModel(Base):
    """Row shape for the `chatwoot_conversation_mappings` table — see
    `app.domain.entities.chatwoot_conversation_mapping.ChatwootConversationMapping`'s
    own docstring."""

    __tablename__ = "chatwoot_conversation_mappings"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    chatwoot_contact_id: Mapped[str] = mapped_column(String, nullable=False)
    chatwoot_conversation_id: Mapped[str] = mapped_column(String, nullable=False)
