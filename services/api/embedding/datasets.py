"""Persistent registry for independently retained embedding datasets."""
from __future__ import annotations

from api.runtime_settings import load_settings, save_settings
from db.pool import sync_pool
from psycopg import sql


def dataset_key(value: dict) -> tuple[str, str, int, str]:
    return (
        str(value["provider"]),
        str(value["model"]),
        int(value["dimension"]),
        str(value.get("base_url") or "").rstrip("/"),
    )


def ensure_dataset(value: dict, *, status: str = "stale") -> int:
    provider, model, dimension, base_url = dataset_key(value)
    with sync_pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO embedding_dataset(provider, model, dimension, base_url, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(provider, model, dimension, base_url) DO UPDATE
            SET updated_at = now()
            RETURNING id
            """,
            (provider, model, dimension, base_url, status),
        ).fetchone()
        conn.commit()
    return int(row[0])


def find_dataset(value: dict) -> dict | None:
    provider, model, dimension, base_url = dataset_key(value)
    with sync_pool.connection() as conn:
        row = conn.execute(
            """
            SELECT id, provider, model, dimension, base_url, status,
                   completed_notices, total_notices, total_chunks, error,
                   completed_at, last_synced_at
            FROM embedding_dataset
            WHERE provider=%s AND model=%s AND dimension=%s AND base_url=%s
            """,
            (provider, model, dimension, base_url),
        ).fetchone()
    if not row:
        return None
    keys = (
        "id", "provider", "model", "dimension", "base_url", "status",
        "completed_notices", "total_notices", "total_chunks", "error",
        "completed_at", "last_synced_at",
    )
    return dict(zip(keys, row))


def get_dataset(dataset_id: int) -> dict | None:
    with sync_pool.connection() as conn:
        row = conn.execute(
            """
            SELECT id, provider, model, dimension, base_url, status,
                   completed_notices, total_notices, total_chunks, error,
                   completed_at, last_synced_at
            FROM embedding_dataset WHERE id=%s
            """,
            (dataset_id,),
        ).fetchone()
    if not row:
        return None
    keys = (
        "id", "provider", "model", "dimension", "base_url", "status",
        "completed_notices", "total_notices", "total_chunks", "error",
        "completed_at", "last_synced_at",
    )
    return dict(zip(keys, row))


def active_dataset_id() -> int:
    active = load_settings()["embedding"]
    existing = find_dataset(active)
    return int(existing["id"]) if existing else ensure_dataset(active, status="ready")


def activate_dataset(dataset_id: int, *, api_key: str = "") -> dict:
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise ValueError("임베딩 데이터셋을 찾을 수 없습니다.")
    if dataset["status"] != "ready" or dataset["completed_at"] is None:
        raise ValueError("완료된 임베딩 데이터셋만 사용할 수 있습니다.")
    settings = load_settings()
    previous = settings["embedding"]
    settings["embedding"] = {
        "provider": dataset["provider"],
        "model": dataset["model"],
        "dimension": dataset["dimension"],
        "base_url": dataset["base_url"],
        "api_key": api_key or (
            previous.get("api_key", "")
            if previous.get("provider") == dataset["provider"] else ""
        ),
    }
    save_settings(settings)
    return dataset


def list_datasets() -> list[dict]:
    active = load_settings()["embedding"]
    active_key = dataset_key(active)
    with sync_pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT ed.id, ed.provider, ed.model, ed.dimension, ed.base_url,
                   ed.status, ed.completed_notices, ed.total_notices,
                   count(nc.id)::int AS actual_chunks,
                   (COALESCE(sum(pg_column_size(nc)), 0)::bigint
                    + COALESCE(pg_relation_size(to_regclass(
                        'idx_notice_chunk_dataset_' || ed.id || '_hnsw'
                      )), 0))::bigint AS bytes,
                   ed.error, ed.created_at, ed.completed_at, ed.last_synced_at
            FROM embedding_dataset ed
            LEFT JOIN notice_chunk nc ON nc.embedding_dataset_id=ed.id
            GROUP BY ed.id
            ORDER BY ed.created_at, ed.id
            """
        ).fetchall()
    keys = (
        "id", "provider", "model", "dimension", "base_url", "status",
        "completed_notices", "total_notices", "total_chunks", "bytes",
        "error", "created_at", "completed_at", "last_synced_at",
    )
    result = []
    for row in rows:
        item = dict(zip(keys, row))
        if item["status"] == "ready" and item["completed_at"] is None:
            item["status"] = "stale"
        item["active"] = dataset_key(item) == active_key
        item["search_mode"] = "hnsw" if int(item["dimension"]) <= 2000 else "exact"
        result.append(item)
    return result


def mark_other_datasets_stale(active_id: int) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            """
            UPDATE embedding_dataset
            SET status='stale', updated_at=now()
            WHERE id<>%s AND status='ready'
            """,
            (active_id,),
        )
        conn.commit()


def delete_dataset(dataset_id: int) -> int:
    if dataset_id == active_dataset_id():
        raise ValueError("현재 사용 중인 임베딩 데이터셋은 삭제할 수 없습니다.")
    with sync_pool.connection() as conn:
        row = conn.execute(
            "SELECT status FROM embedding_dataset WHERE id=%s", (dataset_id,)
        ).fetchone()
        if not row:
            raise ValueError("임베딩 데이터셋을 찾을 수 없습니다.")
        if row[0] == "building":
            raise ValueError("생성 중인 데이터셋은 삭제할 수 없습니다.")
        count = conn.execute(
            "SELECT count(*) FROM notice_chunk WHERE embedding_dataset_id=%s",
            (dataset_id,),
        ).fetchone()[0]
        conn.execute(
            sql.SQL("DROP INDEX IF EXISTS {}").format(
                sql.Identifier(f"idx_notice_chunk_dataset_{dataset_id}_hnsw")
            )
        )
        conn.execute("DELETE FROM embedding_dataset WHERE id=%s", (dataset_id,))
        conn.commit()
    return int(count)


def ensure_search_index(dataset_id: int, dimension: int) -> str:
    if dimension > 2000:
        return "exact"
    index_name = f"idx_notice_chunk_dataset_{dataset_id}_hnsw"
    with sync_pool.connection() as conn:
        conn.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON notice_chunk USING hnsw "
                "((embedding::vector({})) vector_cosine_ops) "
                "WHERE embedding_dataset_id = {}"
            ).format(
                sql.Identifier(index_name),
                sql.SQL(str(dimension)),
                sql.SQL(str(dataset_id)),
            )
        )
        conn.commit()
    return "hnsw"
