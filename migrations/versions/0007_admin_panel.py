"""admin panel: admin_users, admin_audit_log

Creates the accounts and audit trail backing the minimal admin panel
(PRD.md §44, §74.3): `admin_users` holds one row per panel account
(`role` one of ADMIN_TECHNICAL/ADMIN_CLINIC/READ_ONLY), `admin_audit_log`
records every login attempt and sensitive access/change made through the
panel. `admin_audit_log.admin_user_id` is deliberately not a foreign key —
a login-failure entry has no valid admin user to reference yet, and the
audit trail must outlive an account even if it were ever deleted.

Revision ID: 0007_admin_panel
Revises: 0006_audio_transcription
Create Date: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_admin_panel"
down_revision: str | None = "0006_audio_transcription"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", ts, nullable=False, server_default=now),
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("admin_user_id", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", ts, nullable=False, server_default=now),
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_table("admin_users")
