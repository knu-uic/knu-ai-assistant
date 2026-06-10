"""Arq 백그라운드 워커.

실행 (SERVER 디렉터리에서, redis 필요):
    arq workers.arq_worker.WorkerSettings

cron 잡:
- poll_notices: NOTICE_POLL_MINUTES 간격으로 공지 증분 수집(run_ingest).
  DB에 있는 글은 건너뛰므로 반복 실행 안전.
"""
import asyncio

from arq import cron
from arq.connections import RedisSettings

from config import NOTICE_POLL_MINUTES, REDIS_URL


async def poll_notices(ctx: dict) -> dict:
    # 크롤+임베딩은 sync·장시간 작업 → 워커 이벤트루프 비블로킹 위해 스레드에서.
    # import도 여기서: 크롤러·임베딩(torch 등) 무거운 의존성을 잡 실행 시점에만 로드.
    from pipelines.ingest import run_ingest

    result = await asyncio.to_thread(run_ingest)
    print(f"📥 공지 폴링 결과: {result}")
    return result


def _cron_minutes(interval: int) -> set[int]:
    """간격(분)을 cron minute 집합으로. 예: 20 → {0, 20, 40}"""
    return set(range(0, 60, interval))


class WorkerSettings:
    functions: list = []
    cron_jobs = [
        cron(
            poll_notices,
            minute=_cron_minutes(NOTICE_POLL_MINUTES),
            # 이전 실행이 안 끝났으면 다음 발화를 건너뜀 — 크롤 중복 실행 방지
            unique=True,
            timeout=1800,
        )
    ]
    redis_settings = RedisSettings.from_dsn(REDIS_URL or "redis://localhost:6379")
