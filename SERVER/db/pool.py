"""FastAPI용 비동기 커넥션 풀.

- min_size=0: 기동 시 DB 연결을 강제하지 않음(클라우드 콜드스타트·테스트 친화).
  풀은 첫 요청에서 연결을 채운다.
- configure: 풀이 만드는 모든 커넥션에 pgvector 어댑터를 1회 등록.
"""
import os

from psycopg_pool import AsyncConnectionPool
from pgvector.psycopg import register_vector_async

from db.schema import DB_URL


async def _configure(conn):
    await register_vector_async(conn)


pool = AsyncConnectionPool(
    conninfo=DB_URL,
    open=False,
    min_size=0,
    max_size=int(os.getenv("DB_POOL_MAX", "10")),
    configure=_configure,
)
