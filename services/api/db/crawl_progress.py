"""Durable latest-crawl snapshot used by the manager UI and crash recovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from db.pool import sync_pool


def save_crawl_progress(snapshot: dict) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO crawl_run_state(singleton, snapshot, updated_at)
            VALUES (true, %s, now())
            ON CONFLICT (singleton) DO UPDATE
            SET snapshot = EXCLUDED.snapshot, updated_at = now()
            """,
            (json.dumps(snapshot, ensure_ascii=False),),
        )
        conn.commit()


def load_crawl_progress() -> dict:
    with sync_pool.connection() as conn:
        row = conn.execute(
            "SELECT snapshot FROM crawl_run_state WHERE singleton = true"
        ).fetchone()
    return dict(row[0]) if row and isinstance(row[0], dict) else {}


def mark_crawl_progress_interrupted() -> bool:
    snapshot = load_crawl_progress()
    if snapshot.get("status") not in {"running", "paused"}:
        return False
    snapshot.update({
        "status": "interrupted",
        "phase": "interrupted",
        "resumable": True,
        "error": "이전 실행이 정상적으로 끝나지 않아 수집이 중단되었습니다.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    save_crawl_progress(snapshot)
    return True


__all__ = [
    "save_crawl_progress",
    "load_crawl_progress",
    "mark_crawl_progress_interrupted",
]
