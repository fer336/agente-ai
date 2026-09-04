from sqlalchemy.orm import DeclarativeBase

from app.infrastructure.database.models import Base

_EXPECTED_TABLES = {
    "patients",
    "contacts",
    "conversations",
    "messages",
    "appointments",
    "appointment_actions",
    "pending_actions",
    "tool_executions",
    "human_handoffs",
    "approved_contents",
    "outbox_events",
    "scheduled_actions",
    "media_processing_jobs",
    "agent_runs",
    "node_executions",
    "errors",
    "admin_users",
    "admin_audit_log",
    "incidents",
    "runtime_agent_config",
}


def test_base_is_a_declarative_base():
    assert issubclass(Base, DeclarativeBase)


def test_base_metadata_registers_the_core_schema_tables():
    assert set(Base.metadata.tables) == _EXPECTED_TABLES


def test_messages_external_message_id_is_unique():
    column = Base.metadata.tables["messages"].c.external_message_id
    assert column.unique or any(
        set(constraint.columns) == {column}
        for constraint in Base.metadata.tables["messages"].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )


def test_appointment_actions_idempotency_key_is_unique():
    column = Base.metadata.tables["appointment_actions"].c.idempotency_key
    assert column.unique


def test_scheduled_actions_idempotency_key_is_unique():
    column = Base.metadata.tables["scheduled_actions"].c.idempotency_key
    assert column.unique


def test_media_processing_jobs_message_id_is_unique():
    column = Base.metadata.tables["media_processing_jobs"].c.message_id
    assert column.unique
