"""DB 커넥션 풀 (async: FastAPI / sync: LangGraph·크롤러·동기 스크립트).

- min_size=0: 기동 시 DB 연결을 강제하지 않음(클라우드 콜드스타트·테스트 친화).
  풀은 첫 요청에서 연결을 채운다.
- configure: 풀이 만드는 모든 커넥션에 pgvector 어댑터를 1회 등록.
"""
import atexit
import os

from psycopg_pool import AsyncConnectionPool, ConnectionPool
from pgvector.psycopg import register_vector, register_vector_async

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

# sync 경로(GRAPH retriever, 크롤러, sync 스크립트)용 풀.
# open=True여도 min_size=0이라 import 시점에 실제 연결은 만들지 않는다.
sync_pool = ConnectionPool(
    conninfo=DB_URL,
    open=True,
    min_size=0,
    max_size=int(os.getenv("DB_POOL_MAX", "10")),
    configure=register_vector,
)

# 인터프리터 종료 시 풀 워커 스레드가 join되지 않아 경고가 뜨는 것 방지.
atexit.register(sync_pool.close)
