"""Blue-green builds for persistent, model-specific embedding datasets."""
from __future__ import annotations

from itertools import groupby
from threading import Lock, Thread

from db.pool import sync_pool
from embedding.datasets import (
    activate_dataset,
    active_dataset_id,
    ensure_dataset,
    ensure_search_index,
    find_dataset,
    get_dataset,
)
from model import get_embeddings


_lock = Lock()
_status: dict = {
    "state": "idle", "completed": 0, "total": 0,
    "target": None, "dataset_id": None,
}
_ADVISORY_LOCK_NAMESPACE = 126348


def rebuild_status() -> dict:
    with _lock:
        return dict(_status)


def _set_status(**values) -> None:
    with _lock:
        _status.update(values)


def _set_dataset(dataset_id: int, **values) -> None:
    allowed = {
        "status", "completed_notices", "total_notices", "total_chunks", "error"
    }
    values = {key: value for key, value in values.items() if key in allowed}
    if not values:
        return
    assignments = [f"{key}=%s" for key in values]
    with sync_pool.connection() as conn:
        conn.execute(
            f"UPDATE embedding_dataset SET {', '.join(assignments)}, updated_at=now() WHERE id=%s",
            (*values.values(), dataset_id),
        )
        conn.commit()


def start_rebuild(target: dict, *, force: bool = False) -> dict:
    with _lock:
        if _status["state"] == "running":
            raise RuntimeError("이미 임베딩 데이터셋 생성이 진행 중입니다.")

    existing = find_dataset(target)
    if existing and existing["status"] == "ready" and not force:
        activate_dataset(existing["id"], api_key=target.get("api_key", ""))
        _set_status(
            state="complete", completed=existing["completed_notices"],
            total=existing["total_notices"], dataset_id=existing["id"],
            target={key: target[key] for key in ("provider", "model", "dimension")},
            reused=True, error=None,
        )
        return rebuild_status()

    dataset_id = existing["id"] if existing else ensure_dataset(target, status="stale")
    if dataset_id == active_dataset_id():
        raise RuntimeError("현재 사용 중인 데이터셋은 다시 생성할 수 없습니다.")
    _set_dataset(dataset_id, status="building", completed_notices=0, error=None)
    _set_status(
        state="running", completed=0, total=0, dataset_id=dataset_id,
        target={key: target[key] for key in ("provider", "model", "dimension")},
        reused=False, error=None,
    )
    Thread(target=_run_rebuild, args=(dict(target), dataset_id), daemon=True).start()
    return rebuild_status()


def resume_dataset(dataset_id: int, *, api_key: str = "") -> dict:
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise RuntimeError("임베딩 데이터셋을 찾을 수 없습니다.")
    return start_rebuild(
        {
            "provider": dataset["provider"], "model": dataset["model"],
            "dimension": dataset["dimension"], "base_url": dataset["base_url"],
            "api_key": api_key,
        },
        force=True,
    )


def recover_interrupted_builds() -> None:
    if rebuild_status()["state"] == "running":
        return
    with sync_pool.connection() as conn:
        dataset_ids = [
            int(row[0]) for row in conn.execute(
                "SELECT id FROM embedding_dataset WHERE status='building'"
            ).fetchall()
        ]
    for dataset_id in dataset_ids:
        with sync_pool.connection() as conn:
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (_ADVISORY_LOCK_NAMESPACE, dataset_id),
            ).fetchone()[0]
            if not acquired:
                continue
            try:
                conn.execute(
                    """
                    UPDATE embedding_dataset
                    SET status='failed',
                        error='서버가 재시작되어 작업이 중단되었습니다. 동기화를 눌러 이어서 생성하세요.',
                        updated_at=now()
                    WHERE id=%s AND status='building'
                    """,
                    (dataset_id,),
                )
                conn.commit()
            finally:
                conn.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (_ADVISORY_LOCK_NAMESPACE, dataset_id),
                )


def sync_stale_datasets() -> None:
    """Refresh retained local datasets after a crawl without activating them."""
    if rebuild_status()["state"] == "running":
        return
    with sync_pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, provider, model, dimension, base_url
            FROM embedding_dataset
            WHERE status='stale'
            ORDER BY id
            """
        ).fetchall()
    active = active_dataset_id()
    for row in rows:
        dataset_id = int(row[0])
        if dataset_id == active:
            continue
        target = {
            "provider": row[1], "model": row[2], "dimension": row[3],
            "base_url": row[4], "api_key": "",
        }
        _set_status(
            state="running", completed=0, total=0, dataset_id=dataset_id,
            target={key: target[key] for key in ("provider", "model", "dimension")},
            reused=False, error=None,
        )
        _run_rebuild(target, dataset_id, activate_when_ready=False)


def _run_rebuild(
    target: dict,
    dataset_id: int | None = None,
    *,
    activate_when_ready: bool = True,
) -> None:
    dataset_id = dataset_id or ensure_dataset(target, status="building")
    with sync_pool.connection() as lock_conn:
        acquired = lock_conn.execute(
            "SELECT pg_try_advisory_lock(%s, %s)",
            (_ADVISORY_LOCK_NAMESPACE, dataset_id),
        ).fetchone()[0]
        if not acquired:
            _set_status(
                state="failed", dataset_id=dataset_id,
                error="다른 프로세스에서 이 데이터셋을 생성 중입니다.",
            )
            return
        try:
            _run_rebuild_body(
                target, dataset_id, activate_when_ready=activate_when_ready
            )
        finally:
            lock_conn.execute(
                "SELECT pg_advisory_unlock(%s, %s)",
                (_ADVISORY_LOCK_NAMESPACE, dataset_id),
            )


def _run_rebuild_body(
    target: dict,
    dataset_id: int,
    *,
    activate_when_ready: bool,
) -> None:
    try:
        source_dataset_id = active_dataset_id()
        with sync_pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT notice_id, chunk_idx, content, chunk_type, attachment_name
                FROM notice_chunk
                WHERE embedding_dataset_id=%s
                ORDER BY notice_id, chunk_idx
                """,
                (source_dataset_id,),
            ).fetchall()

        grouped = [
            (notice_id, list(items))
            for notice_id, items in groupby(rows, key=lambda row: row[0])
        ]
        _set_status(total=len(grouped), dataset_id=dataset_id)
        _set_dataset(
            dataset_id, status="building", total_notices=len(grouped),
            completed_notices=0, error=None,
        )
        embedder = get_embeddings(target)

        for completed, (notice_id, chunks) in enumerate(grouped, start=1):
            texts = [row[2] for row in chunks]
            vectors = embedder.embed_documents(texts)
            if any(len(vector) != int(target["dimension"]) for vector in vectors):
                raise RuntimeError("선택한 출력 차원과 실제 임베딩 차원이 다릅니다.")
            with sync_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM notice_chunk WHERE notice_id=%s AND embedding_dataset_id=%s",
                    (notice_id, dataset_id),
                )
                for row, vector in zip(chunks, vectors):
                    conn.execute(
                        """
                        INSERT INTO notice_chunk
                            (notice_id, chunk_idx, content, chunk_type,
                             attachment_name, embedding, embedding_provider,
                             embedding_model, embedding_dimension, embedding_dataset_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            notice_id, row[1], row[2], row[3], row[4], vector,
                            target["provider"], target["model"], target["dimension"],
                            dataset_id,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE embedding_dataset
                    SET completed_notices=%s,
                        total_chunks=(SELECT count(*) FROM notice_chunk WHERE embedding_dataset_id=%s),
                        updated_at=now()
                    WHERE id=%s
                    """,
                    (completed, dataset_id, dataset_id),
                )
                conn.commit()
            _set_status(completed=completed)

        with sync_pool.connection() as conn:
            total_chunks = conn.execute(
                "SELECT count(*) FROM notice_chunk WHERE embedding_dataset_id=%s",
                (dataset_id,),
            ).fetchone()[0]
            conn.execute(
                """
                UPDATE embedding_dataset
                SET status='ready', completed_notices=%s, total_notices=%s,
                    total_chunks=%s, error=NULL, completed_at=now(),
                    last_synced_at=now(), updated_at=now()
                WHERE id=%s
                """,
                (len(grouped), len(grouped), total_chunks, dataset_id),
            )
            conn.commit()
        ensure_search_index(dataset_id, int(target["dimension"]))
        if activate_when_ready:
            activate_dataset(dataset_id, api_key=target.get("api_key", ""))
        _set_status(
            state="complete", completed=len(grouped), total=len(grouped),
            dataset_id=dataset_id,
        )
    except Exception as exc:
        if dataset_id is not None:
            _set_dataset(dataset_id, status="failed", error=str(exc))
        _set_status(state="failed", error=str(exc), dataset_id=dataset_id)
