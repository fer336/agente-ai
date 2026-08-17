"""observability: agent_runs, node_executions, tool_executions, errors

Creates the functional-traceability schema (PRD.md §38-42): one `agent_run`
per message processed by the graph, one `node_execution` per LangGraph node
call within a run, one `tool_execution` per external service call, and one
`error` record per error encountered anywhere in the system. `*_summary`
columns are short text summaries, never raw payloads (PRD.md §41's privacy
mandate). `error_id` columns on `agent_runs`/`node_executions`/
`tool_executions` are plain (non-FK) — a real FK to `errors.id` would form
a circular reference with `errors.agent_run_id`, and the back-reference is
informational, not a referential-integrity requirement.

Revision ID: 0005_observability
Revises: 0004_conversation_input_state
Create Date: 2026-08-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_observability"
down_revision: str | None = "0004_conversation_input_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("message_id", sa.String(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("started_at", ts, nullable=False),
        sa.Column("finished_at", ts, nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_node", sa.String(), nullable=True),
        sa.Column("error_id", sa.String(), nullable=True),
    )

    op.create_table(
        "node_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("started_at", ts, nullable=False),
        sa.Column("finished_at", ts, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_id", sa.String(), nullable=True),
    )

    op.drop_table("tool_executions")

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column(
            "node_execution_id", sa.String(), sa.ForeignKey("node_executions.id"), nullable=True
        ),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("request_summary", sa.Text(), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("http_status", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_id", sa.String(), nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=now),
    )

    op.create_table(
        "errors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column(
            "conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=True
        ),
        sa.Column("agent_run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("technical_detail", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
        sa.Column("resolved_at", ts, nullable=True),
    )
    op.create_index("ix_errors_source_error_type", "errors", ["source", "error_type"])


def downgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.drop_index("ix_errors_source_error_type", table_name="errors")
    op.drop_table("errors")
    op.drop_table("tool_executions")
    op.drop_table("node_executions")
    op.drop_table("agent_runs")

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
