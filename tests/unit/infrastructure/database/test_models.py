from sqlalchemy.orm import DeclarativeBase

from app.infrastructure.database.models import Base


def test_base_is_an_empty_declarative_base():
    assert issubclass(Base, DeclarativeBase)
    assert list(Base.metadata.tables) == []
