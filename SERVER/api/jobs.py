"""API → Arq 잡 enqueue용 redis 풀 (lazy 싱글턴)."""
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from config import REDIS_URL

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(
            RedisSettings.from_dsn(REDIS_URL or "redis://localhost:6379")
        )
    return _pool
