"""Arq 백그라운드 워커.

실행 (SERVER 디렉터리에서, redis 필요):
    arq workers.arq_worker.WorkerSettings

잡:
- poll_notices(cron): NOTICE_POLL_MINUTES 간격으로 공지 증분 수집(run_ingest).
  DB에 있는 글은 건너뛰므로 반복 실행 안전.
- portal_sync: 포털 로그인→시간표·성적·졸업정보 동기화. 비밀번호는 암호문으로
  받아 복호화해 쓰고 폐기. 진행 단계는 redis 키(portal-sync:step:{job_id})로 노출.
"""
import asyncio

import redis as redis_sync
from arq import cron
from arq.connections import RedisSettings

from config import NOTICE_POLL_MINUTES, PORTAL_SYNC_TIMEOUT_SECONDS, REDIS_URL

STEP_KEY_PREFIX = "portal-sync:step:"
STEP_TTL_SECONDS = 600


def step_key(job_id: str) -> str:
    return f"{STEP_KEY_PREFIX}{job_id}"


async def portal_sync(ctx: dict, username: str, student_id: str, enc_password: str) -> dict:
    """포털 동기화 1회. 성공 시 accounts.student_id 연결까지 수행한다."""
    from api.crypto import decrypt_secret
    from db.accounts import link_student_id
    from sync.knuis_sync import run_portal_sync

    job_id = ctx.get("job_id", "")
    # 진행 단계 기록은 sync 콜백(스레드)에서 일어나므로 sync redis 클라이언트 사용.
    r = redis_sync.from_url(REDIS_URL or "redis://localhost:6379")

    def on_step(msg: str) -> None:
        r.set(step_key(job_id), msg, ex=STEP_TTL_SECONDS)

    password = decrypt_secret(enc_password)
    try:
        result = await asyncio.to_thread(
            run_portal_sync, student_id, password, on_step=on_step
        )
    finally:
        del password  # 사용 즉시 참조 제거 (영속화 없음)

    if result.get("success"):
        await asyncio.to_thread(link_student_id, username, student_id)
    r.close()
    return result


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
    functions = [portal_sync]
    # 포털 동기화는 Playwright 동시 실행 RAM 피크 제한 — 워커당 잡 2개까지
    max_jobs = 2
    job_timeout = PORTAL_SYNC_TIMEOUT_SECONDS
    # 완료 결과 보존 2분 — 폴링 클라이언트가 읽을 시간. 지나면 같은 유저 재동기화 가능
    keep_result = 120
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
