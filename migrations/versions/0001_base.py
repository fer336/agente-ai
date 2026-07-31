"""base

Empty/no-op base revision. Proves the Alembic pipeline (env.py wiring,
connectivity to Postgres via app.config.settings.DATABASE_URL) without
introducing any schema yet — the real domain schema is Etapa 1 work.

Revision ID: 0001_base
Revises:
Create Date: 2026-07-31

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op — proves the migration pipeline runs end to end."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
