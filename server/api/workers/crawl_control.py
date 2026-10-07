"""Shared control keys and cleanup helpers for the notice crawler."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from config import REDIS_URL
from db.crawl_progress import mark_crawl_progress_interrupted

NOTICE_CRAWL_ACTIVE_KEY = "notice-crawl:active"
NOTICE_CRAWL_PAUSE_KEY = "notice-crawl:pause"
NOTICE_CRAWL_STOP_KEY = "notice-crawl:stop"
NOTICE_CRAWL_PROGRESS_KEY = "notice-crawl:progress"
NOTICE_CRAWL_PENDING_KEY = "notice-crawl:pending"
MANUAL_NOTICE_JOB_PREFIX = "manual-notice-crawl"


def cleanup_interrupted_crawl() -> int:
    """Release dead worker locks while preserving the crawl list for recovery.

    Persisted notices and URL registry rows live in PostgreSQL and are deliberately
    untouched. The progress snapshot is also retained so the UI can show exactly
    where an interrupted run stopped and offer a resume action.
    """
    import redis

    client = redis.from_url(REDIS_URL or "redis://localhost:6379")
    try:
        mark_crawl_progress_interrupted()
        job_ids = {MANUAL_NOTICE_JOB_PREFIX}
        for key in (NOTICE_CRAWL_ACTIVE_KEY, NOTICE_CRAWL_PENDING_KEY):
            value = client.get(key)
            if value:
                job_ids.add(value.decode() if isinstance(value, bytes) else str(value))
        # A hard kill can happen after ARQ persists the unique queued job but
        # before poll_notices writes active/pending. Recover those UUID-suffixed
        # manager jobs as well so a new worker cannot silently restart one.
        for value in client.zrange("arq:queue", 0, -1):
            job_id = value.decode() if isinstance(value, bytes) else str(value)
            if job_id == MANUAL_NOTICE_JOB_PREFIX or job_id.startswith(
                f"{MANUAL_NOTICE_JOB_PREFIX}-"
            ):
                job_ids.add(job_id)

        raw_progress = client.get(NOTICE_CRAWL_PROGRESS_KEY)
        if raw_progress:
            try:
                progress = json.loads(
                    raw_progress.decode() if isinstance(raw_progress, bytes) else raw_progress
                )
            except (TypeError, ValueError, UnicodeDecodeError):
                progress = None
            if isinstance(progress, dict) and progress.get("status") in {"running", "paused"}:
                progress.update({
                    "status": "interrupted",
                    "phase": "interrupted",
                    "resumable": True,
                    "error": "이전 실행이 정상적으로 끝나지 않아 수집이 중단되었습니다.",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                client.set(
                    NOTICE_CRAWL_PROGRESS_KEY,
                    json.dumps(progress, ensure_ascii=False),
                )

        job_keys = [
            f"arq:{kind}:{job_id}"
            for job_id in job_ids
            for kind in ("job", "retry", "in-progress", "result")
        ]
        removed = client.delete(
            NOTICE_CRAWL_ACTIVE_KEY,
            NOTICE_CRAWL_PAUSE_KEY,
            NOTICE_CRAWL_STOP_KEY,
            NOTICE_CRAWL_PENDING_KEY,
            *job_keys,
        )
        removed += client.zrem("arq:queue", *job_ids)
        return int(removed)
    finally:
        client.close()
