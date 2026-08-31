"""incidents

Creates the `incidents` table backing incident deduplication (PRD.md §49):
one row per `fingerprint` (`source:error_type:operation`), updated in place
on repeat occurrences rather than duplicated. `errors` deliberately does NOT
gain an `operation` column here — `ErrorRepository.count_recent`'s own
docstring already documents that `errors` groups only by `source`+
`error_type`; `operation` is threaded as a plain parameter into
`ErrorService.report()`/`build_fingerprint` and persisted only on
`incidents`, not retrofitted onto the existing `errors` table.

Revision ID: 0008_incidents
Revises: 0007_admin_panel
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_incidents"
down_revision: str | None = "0007_admin_panel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    now = sa.func.now()

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("affected_conversations", sa.Integer(), nullable=False),
        sa.Column("first_seen", ts, nullable=False),
        sa.Column("last_seen", ts, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("linear_issue_id", sa.String(), nullable=True),
        sa.Column("last_notification_at", ts, nullable=True),
        sa.Column("resolved_at", ts, nullable=True),
        sa.Column("created_at", ts, nullable=False, server_default=now),
    )
    # Not a UNIQUE index: `status` is part of the row, and a RECOVERED
    # incident with the same fingerprint must be able to coexist with a
    # later, separate OPEN incident (a service that broke, recovered, then
    # broke again is two distinct incidents in PRD.md §49/§51's model, not
    # one reopened row) — `get_by_fingerprint` filters to `status='open'`
    # itself instead.
    op.create_index("ix_incidents_fingerprint", "incidents", ["fingerprint"])
    op.create_index("ix_incidents_status", "incidents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_fingerprint", table_name="incidents")
    op.drop_table("incidents")
