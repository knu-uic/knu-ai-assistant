"""Isolated notice-ingest entrypoint used for immediate pause/stop control."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import traceback

import redis

from config import REDIS_URL


def _watch_parent(parent_pid: int) -> None:
    """Kill this process group if the ARQ worker disappears unexpectedly."""
    while True:
        time.sleep(0.25)
        if os.getppid() == parent_pid:
            continue
        if os.name == "nt":
            os._exit(1)
        os.killpg(os.getpid(), signal.SIGKILL)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: crawl_subprocess EVENT_KEY REQUEST_JSON")

    event_key = sys.argv[1]
    request = json.loads(sys.argv[2])
    client = redis.from_url(REDIS_URL or "redis://localhost:6379")
    parent_pid = os.getppid()
    threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()

    def publish(kind: str, value) -> None:
        client.rpush(
            event_key,
            json.dumps({"kind": kind, "value": value}, ensure_ascii=False, default=str),
        )
        client.expire(event_key, 3600)

    try:
        from pipelines.ingest import run_ingest

        result = run_ingest(request, on_progress=lambda update: publish("progress", update))
        publish("result", result)
        return 0
    except BaseException as exc:
        publish("error", {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        })
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
