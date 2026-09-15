"""Arq 백그라운드 워커.

실행 (`services/api` 디렉터리에서, Redis 필요):
    arq workers.arq_worker.WorkerSettings

잡:
- poll_notices(cron): NOTICE_POLL_MINUTES 간격으로 공지 증분 수집(run_ingest).
  DB에 있는 글은 건너뛰므로 반복 실행 안전.
- portal_sync: 포털 로그인→시간표·성적·졸업정보 동기화. 비밀번호는 암호문으로
  받아 복호화해 쓰고 폐기. 진행 단계는 redis 키(portal-sync:step:{job_id})로 노출.
"""
import asyncio
import json
from datetime import datetime, timezone

import redis as redis_sync
from arq import cron
from arq.connections import RedisSettings
from arq.worker import func

from config import PORTAL_SYNC_TIMEOUT_SECONDS, REDIS_URL
from api.runtime_settings import load_settings

STEP_KEY_PREFIX = "portal-sync:step:"
STEP_TTL_SECONDS = 600
NOTICE_CRAWL_PROGRESS_KEY = "notice-crawl:progress"
NOTICE_CRAWL_PROGRESS_TTL_SECONDS = 86400


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


def _run_lms_sync_blocking(username: str, student_id: str, password: str | None, on_step) -> dict:
    """LMS 동기화 (sync, 스레드에서 실행).

    분기:
    - 비번 있음 → 로그인(브라우저)으로 세션 새로 발급·저장 → 동기화
    - 비번 없음 + 저장된 세션 있음 → 세션만으로 동기화 (브라우저 없음)
    - 비번 없음 + 세션 없음/만료 → needs_reconnect (앱이 비번 재제출)
    """
    import tempfile
    from pathlib import Path

    from sync.common import canvas_token_path
    from sync.lms_login import login_with_credentials
    from sync.lms_sync import run_lms_sync
    from api.sessions import load_session, save_session

    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "lms_storage_state.json"
        token_path = canvas_token_path(state_path)

        session = load_session(username)
        if session:
            state_path.write_text(session["storage_state"], encoding="utf-8")
            if session.get("canvas_token"):
                token_path.write_text(session["canvas_token"], encoding="utf-8")

        if password:
            on_step("LMS 로그인 중")
            login_with_credentials(student_id, password, state=str(state_path))

        if not state_path.exists():
            # 세션도 비번도 없음 — 앱에 재연결(비번 재제출) 요청
            return {"success": False, "needs_reconnect": True,
                    "message": "포털 재연결이 필요합니다."}

        try:
            result = run_lms_sync(student_id, state_path=state_path, on_step=on_step)
        except Exception as e:
            # 비번 없이 재사용한 세션이 만료된 경우 — 재연결 요청으로 안내
            if not password:
                return {"success": False, "needs_reconnect": True,
                        "message": "세션이 만료되었습니다. 다시 연결해주세요."}
            raise

        # 로그인으로 세션이 갱신됐으면 Redis에 저장 (다음 동기화는 비번 없이)
        if password and state_path.exists():
            token = token_path.read_text(encoding="utf-8") if token_path.exists() else None
            save_session(username, state_path.read_text(encoding="utf-8"), token)

        return result


async def lms_sync(ctx: dict, username: str, student_id: str, enc_password: str | None) -> dict:
    from api.crypto import decrypt_secret

    job_id = ctx.get("job_id", "")
    r = redis_sync.from_url(REDIS_URL or "redis://localhost:6379")

    def on_step(msg: str) -> None:
        r.set(step_key(job_id), msg, ex=STEP_TTL_SECONDS)

    password = decrypt_secret(enc_password) if enc_password else None
    try:
        return await asyncio.to_thread(
            _run_lms_sync_blocking, username, student_id, password, on_step
        )
    finally:
        if password:
            del password
        r.close()


async def counseling_prepare(
    ctx: dict, student_id: str, advisor: str | None = None, mode: str = "online"
) -> dict:
    from api.sessions import load_portal_session
    from sync.counseling import prepare_online_counseling

    storage_state = await asyncio.to_thread(load_portal_session, student_id)
    if storage_state is None:
        return {"success": False, "needs_reconnect": True,
                "message": "포털 세션이 만료되었습니다. Codmes에서 포털을 다시 연결해주세요."}
    return await asyncio.to_thread(
        prepare_online_counseling, student_id, storage_state, advisor, mode
    )


async def counseling_submit(
    ctx: dict,
    student_id: str,
    advisor: str,
    mode: str,
    date: str | None,
    time_text: str | None,
    title: str,
    content: str,
    topics: list[str],
) -> dict:
    from api.sessions import load_portal_session
    from sync.counseling import submit_online_counseling

    storage_state = await asyncio.to_thread(load_portal_session, student_id)
    if storage_state is None:
        return {"success": False, "needs_reconnect": True,
                "message": "포털 세션이 만료되었습니다. Codmes에서 포털을 다시 연결해주세요."}
    return await asyncio.to_thread(
        submit_online_counseling, student_id, storage_state, advisor, mode, date, time_text,
        title, content, topics
    )


async def keep_portal_session(ctx: dict, student_id: str) -> dict:
    """Refresh an existing portal session without storing or using a password."""
    from api.sessions import load_portal_session, save_portal_session
    from sync.portal_auth import refresh_portal_session

    storage_state = await asyncio.to_thread(load_portal_session, student_id)
    if storage_state is None:
        return {"success": False, "needs_reconnect": True}
    refreshed_state = await asyncio.to_thread(
        refresh_portal_session, student_id, storage_state
    )
    if refreshed_state is None:
        return {"success": False, "needs_reconnect": True}
    await asyncio.to_thread(save_portal_session, student_id, refreshed_state)
    return {"success": True}


async def poll_notices(ctx: dict, crawl_request: dict | None = None) -> dict:
    redis = ctx.get("redis")
    lock_key = "notice-crawl:active"
    if redis is not None:
        acquired = await redis.set(lock_key, ctx.get("job_id", "crawler"), ex=25200, nx=True)
        if not acquired:
            return {"skipped": True, "reason": "already_running"}
    # 크롤+임베딩은 sync·장시간 작업 → 워커 이벤트루프 비블로킹 위해 스레드에서.
    # import도 여기서: 크롤러·임베딩(torch 등) 무거운 의존성을 잡 실행 시점에만 로드.
    from pipelines.ingest import run_ingest

    progress_redis = redis_sync.from_url(REDIS_URL or "redis://localhost:6379")
    progress = {
        "job_id": ctx.get("job_id", "crawler"),
        "status": "running",
        "phase": "starting",
        "discovered": 0,
        "processed": 0,
        "saved": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    def publish_progress(update: dict) -> None:
        for key, value in update.items():
            if key.endswith("_increment"):
                target = key.removesuffix("_increment")
                progress[target] = int(progress.get(target, 0)) + int(value)
            else:
                progress[key] = value
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress_redis.set(
            NOTICE_CRAWL_PROGRESS_KEY,
            json.dumps(progress, ensure_ascii=False),
            ex=NOTICE_CRAWL_PROGRESS_TTL_SECONDS,
        )

    publish_progress({})

    try:
        result = await asyncio.to_thread(
            run_ingest, crawl_request, on_progress=publish_progress
        )
        publish_progress({"status": "complete", "phase": "complete", "result": result})
        print(f"📥 공지 폴링 결과: {result}")
        return result
    except BaseException as exc:
        publish_progress({
            "status": "stopped" if isinstance(exc, asyncio.CancelledError) else "failed",
            "phase": "stopped" if isinstance(exc, asyncio.CancelledError) else "failed",
            "error": "" if isinstance(exc, asyncio.CancelledError) else str(exc),
        })
        raise
    finally:
        progress_redis.close()
        if redis is not None:
            await redis.delete(lock_key)


async def scheduled_poll_notices(ctx: dict) -> dict:
    """매시 확인하되 설정된 1/6/12/24시간 경계에서만 수집한다."""
    from datetime import datetime, timezone

    settings = load_settings()
    if not settings["crawl_enabled"]:
        return {"skipped": True, "reason": "automatic_crawl_disabled"}
    interval = settings["crawl_interval_hours"]
    hour = datetime.now(timezone.utc).hour
    if hour % interval:
        return {"skipped": True, "interval_hours": interval}
    return await poll_notices(ctx, settings["crawl_request"])


async def scheduled_portal_keepalive(ctx: dict) -> dict:
    """Refresh every stored portal session sequentially to cap browser usage."""
    from api.sessions import portal_session_student_ids

    results = []
    for student_id in await asyncio.to_thread(portal_session_student_ids):
        results.append(await keep_portal_session(ctx, student_id))
    return {
        "refreshed": sum(result.get("success", False) for result in results),
        "needs_reconnect": sum(result.get("needs_reconnect", False) for result in results),
    }


class WorkerSettings:
    # 크롤링은 대용량 첨부·재시도를 포함하므로 포털 동기화(3분)와 다른 timeout을 쓴다.
    functions = [portal_sync, lms_sync, counseling_prepare, counseling_submit, keep_portal_session, func(poll_notices, timeout=21600)]
    # 포털 동기화는 Playwright 동시 실행 RAM 피크 제한 — 워커당 잡 2개까지
    max_jobs = 2
    job_timeout = PORTAL_SYNC_TIMEOUT_SECONDS
    # 완료 결과 보존 2분 — 폴링 클라이언트가 읽을 시간. 지나면 같은 유저 재동기화 가능
    keep_result = 120
    cron_jobs = [
        cron(
            scheduled_poll_notices,
            minute={0},
            # 이전 실행이 안 끝났으면 다음 발화를 건너뜀 — 크롤 중복 실행 방지
            unique=True,
            timeout=21600,
        ),
        cron(scheduled_portal_keepalive, minute=set(range(0, 60, 10)), unique=True),
    ]
    redis_settings = RedisSettings.from_dsn(REDIS_URL or "redis://localhost:6379")
