"""Blue-green embedding rebuilds for local Server Manager model changes."""
from __future__ import annotations

from itertools import groupby
from threading import Lock, Thread

from api.runtime_settings import load_settings, save_settings
from db.pool import sync_pool
from model import get_embeddings


_lock = Lock()
_status: dict = {"state": "idle", "completed": 0, "total": 0, "target": None}


def rebuild_status() -> dict:
    with _lock:
        return dict(_status)


def start_rebuild(target: dict) -> dict:
    with _lock:
        if _status["state"] == "running":
            raise RuntimeError("이미 임베딩 교체가 진행 중입니다.")
        _status.update({
            "state": "running",
            "completed": 0,
            "total": 0,
            "target": {
                "provider": target["provider"],
                "model": target["model"],
                "dimension": target["dimension"],
            },
            "error": None,
        })
    Thread(target=_run_rebuild, args=(dict(target),), daemon=True).start()
    return rebuild_status()


def _set_status(**values) -> None:
    with _lock:
        _status.update(values)


def _run_rebuild(target: dict) -> None:
    try:
        current_settings = load_settings()
        active = current_settings["embedding"]
        if (
            active["provider"] == target["provider"]
            and active["model"] == target["model"]
        ):
            current_settings["embedding"] = target
            save_settings(current_settings)
            _set_status(state="complete", completed=0, total=0)
            return

        with sync_pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT notice_id, chunk_idx, content, chunk_type, attachment_name
                FROM notice_chunk
                WHERE embedding_provider = %s AND embedding_model = %s
                ORDER BY notice_id, chunk_idx
                """,
                (active["provider"], active["model"]),
            ).fetchall()

        grouped = [
            (notice_id, list(items))
            for notice_id, items in groupby(rows, key=lambda row: row[0])
        ]
        _set_status(total=len(grouped))
        embedder = get_embeddings(target)

        for completed, (notice_id, chunks) in enumerate(grouped, start=1):
            texts = [row[2] for row in chunks]
            vectors = embedder.embed_documents(texts)
            if any(len(vector) != target["dimension"] for vector in vectors):
                raise RuntimeError("선택한 모델의 임베딩 차원이 연결 테스트 결과와 달라졌습니다.")
            with sync_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM notice_chunk WHERE notice_id = %s "
                    "AND embedding_provider = %s AND embedding_model = %s",
                    (notice_id, target["provider"], target["model"]),
                )
                for row, vector in zip(chunks, vectors):
                    conn.execute(
                        """
                        INSERT INTO notice_chunk
                            (notice_id, chunk_idx, content, chunk_type,
                             attachment_name, embedding, embedding_provider,
                             embedding_model, embedding_dimension)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            notice_id, row[1], row[2], row[3], row[4], vector,
                            target["provider"], target["model"], target["dimension"],
                        ),
                    )
                conn.commit()
            _set_status(completed=completed)

        latest = load_settings()
        latest["embedding"] = target
        save_settings(latest)
        _set_status(state="complete", completed=len(grouped), total=len(grouped))
    except Exception as exc:
        _set_status(state="failed", error=str(exc))
