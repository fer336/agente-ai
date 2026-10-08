from sqlalchemy import DateTime

from app.infrastructure.database.models import Base


def test_contacts_review_opt_out_timestamp_is_nullable_and_timezone_aware():
    column = Base.metadata.tables["contacts"].c.review_opted_out_at

    assert column.nullable
    assert isinstance(column.type, DateTime)
    assert column.type.timezone
