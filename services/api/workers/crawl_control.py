"""Shared control keys and cleanup helpers for the notice crawler."""

from __future__ import annotations

from config import REDIS_URL

NOTICE_CRAWL_ACTIVE_KEY = "notice-crawl:active"
NOTICE_CRAWL_PAUSE_KEY = "notice-crawl:pause"
NOTICE_CRAWL_STOP_KEY = "notice-crawl:stop"
NOTICE_CRAWL_PROGRESS_KEY = "notice-crawl:progress"
NOTICE_CRAWL_PENDING_KEY = "notice-crawl:pending"
MANUAL_NOTICE_JOB_PREFIX = "manual-notice-crawl"


def cleanup_interrupted_crawl() -> int:
    """Remove only transient state left by an interrupted manager-owned crawl.

    Persisted notices and URL registry rows live in PostgreSQL and are deliberately
    untouched. The next manual run can therefore resume by skipping completed URLs.
    """
    import redis

    client = redis.from_url(REDIS_URL or "redis://localhost:6379")
    try:
        job_ids = {MANUAL_NOTICE_JOB_PREFIX}
        for key in (NOTICE_CRAWL_ACTIVE_KEY, NOTICE_CRAWL_PENDING_KEY):
            value = client.get(key)
            if value:
                job_ids.add(value.decode() if isinstance(value, bytes) else str(value))

        job_keys = [
            f"arq:{kind}:{job_id}"
            for job_id in job_ids
            for kind in ("job", "retry", "in-progress", "result")
        ]
        removed = client.delete(
            NOTICE_CRAWL_ACTIVE_KEY,
            NOTICE_CRAWL_PAUSE_KEY,
            NOTICE_CRAWL_STOP_KEY,
            NOTICE_CRAWL_PROGRESS_KEY,
            NOTICE_CRAWL_PENDING_KEY,
            *job_keys,
        )
        removed += client.zrem("arq:queue", *job_ids)
        return int(removed)
    finally:
        client.close()
