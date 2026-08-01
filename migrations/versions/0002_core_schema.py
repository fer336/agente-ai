"""core schema

Creates the tables backed by a domain entity or an explicit column spec in
the architecture doc (sections 5.4, 5.8, 10, 12.2 and 13): patients, contacts,
conversations, messages, appointments, appointment_actions, pending_actions,
tool_executions, human_handoffs, approved_contents and outbox_events.

`conversation_states`, `prompt_versions`, `agent_runs`, `errors` and
`system_settings` are listed in §5.8 but have no domain entity or column
spec yet, so they are deferred to a later change.

Revision ID: 0002_core_schema
Revises: 0001_base
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_core_schema"
down_revision: str | None = "0001_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.create_table(
        "patients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("updated_at", ts, nullable=True),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("updated_at", ts, nullable=True),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("contact_id", sa.String(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("updated_at", ts, nullable=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("external_message_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.UniqueConstraint("external_message_id", name="uq_messages_external_message_id"),
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("professional_id", sa.String(), nullable=False),
        sa.Column("specialty_id", sa.String(), nullable=False),
        sa.Column("start_at", ts, nullable=False),
        sa.Column("end_at", ts, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("updated_at", ts, nullable=True),
    )

    op.create_table(
        "appointment_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("appointment_id", sa.String(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("executed_at", ts, nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_appointment_actions_idempotency_key"),
    )

    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("confirmation_token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", ts, nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("confirmed_at", ts, nullable=True),
        sa.Column("executed_at", ts, nullable=True),
    )

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_run_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
    )

    op.create_table(
        "human_handoffs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("resolved_at", ts, nullable=True),
    )

    op.create_table(
        "approved_contents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("updated_at", ts, nullable=True),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", ts, nullable=False, server_default=now),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("processed_at", ts, nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("approved_contents")
    op.drop_table("human_handoffs")
    op.drop_table("tool_executions")
    op.drop_table("pending_actions")
    op.drop_table("appointment_actions")
    op.drop_table("appointments")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("contacts")
    op.drop_table("patients")
