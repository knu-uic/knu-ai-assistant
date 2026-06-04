from psycopg_pool import AsyncConnectionPool
from db.pool import pool


def test_pool_is_async_and_lazy():
    assert isinstance(pool, AsyncConnectionPool)
    assert pool.min_size == 0
    assert pool.max_size >= 1
