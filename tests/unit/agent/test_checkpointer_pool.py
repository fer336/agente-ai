"""Connection-hygiene tests for the checkpointer's own psycopg pool.

Pure unit tests — `create_postgres_checkpointer_pool` returns the pool
unopened (`open=False`), so nothing here touches a real Postgres.
"""

import pytest

pytest.importorskip("psycopg_pool", reason="psycopg[binary,pool] not installed in this environment")

from psycopg_pool import AsyncConnectionPool

from app.agent.graph import create_postgres_checkpointer_pool

_CONNINFO = "postgresql://user:pass@localhost:5432/db"


def test_pool_validates_connections_before_handing_them_out():
    # Without a `check`, psycopg_pool hands out a connection the server has
    # since dropped (restart, idle reaper, network blip) and the query dies
    # with `consuming input failed: server closed the connection
    # unexpectedly` — seen live in production, killing every agent turn at
    # `aget_state`. This is the psycopg equivalent of the SQLAlchemy
    # engine's own `pool_pre_ping=True`.
    pool = create_postgres_checkpointer_pool(_CONNINFO)

    assert pool._check is AsyncConnectionPool.check_connection


def test_pool_recycles_connections_well_before_the_default_hour():
    # psycopg_pool's 3600s default keeps a dead-but-pooled connection in
    # rotation for up to an hour; a middlebox/cloud idle reaper typically
    # cuts well before that.
    pool = create_postgres_checkpointer_pool(_CONNINFO)

    assert pool.max_lifetime <= 1800
