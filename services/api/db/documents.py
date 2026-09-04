from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from db.pool import sync_pool
from db.schema import _months_ago


NOTICE_CATEGORIES = ("장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)")
CURRENT_NOTICE_EXTRACTION_VERSION = "notice-v5"
NOTICE_PERIOD_KINDS = (
    "application",
    "document_submission",
    "result_announcement",
    "event",
    "registration",
    "payment",
    "other",
)
NOTICE_AUDIENCE_KINDS = (
    "department",
    "grade",
    "enrollment_status",
    "eligibility",
)


def _plain(value: Any) -> dict:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def _clean_date(value):
    if value is None or not str(value).strip():
        return None
    return value


def archive_documents(
    retention_months: int = 24,
    protected_urls: set[str] | None = None,
) -> int:
    """오래된 공지는 메타데이터만 남기고 원문·첨부·임베딩을 경량화한다."""
    cutoff = _months_ago(date.today(), retention_months)
    protected_urls = protected_urls or set()
    with sync_pool.connection() as conn:
        rows = conn.execute(
            """
            UPDATE notice
            SET archived_at = now(),
                archive_reason = 'retention',
                content = '',
                body_content = NULL,
                updated_at = now()
            WHERE archived_at IS NULL
              AND NOT is_pinned
              AND NOT preserve_forever
              AND NOT (url = ANY(%s))
              AND COALESCE(posted_at, crawled_at::date) < %s
            RETURNING id
            """,
            (list(protected_urls), cutoff),
        ).fetchall()
        notice_ids = [row[0] for row in rows]
        if notice_ids:
            conn.execute(
                "DELETE FROM notice_chunk WHERE notice_id = ANY(%s)",
                (notice_ids,),
            )
            conn.execute(
                "DELETE FROM notice_asset WHERE notice_id = ANY(%s)",
                (notice_ids,),
            )
        conn.commit()

    print(
        f"🗄️ 공지 경량 보관 완료: {len(notice_ids)}건 "
        f"(전체 보존 {retention_months}개월, 보호 URL {len(protected_urls)}건)"
    )
    return len(notice_ids)


def sync_pinned_urls(pinned_urls: set[str]) -> None:
    with sync_pool.connection() as conn:
        conn.execute("UPDATE notice SET is_pinned = false WHERE is_pinned = true")
        if pinned_urls:
            conn.execute(
                "UPDATE notice SET is_pinned = true WHERE url = ANY(%s)",
                (list(pinned_urls),),
            )
        conn.commit()
    print(f"📌 고정 공지 동기화 완료: 현재 고정 URL {len(pinned_urls)}건")


def upsert_source(
    code: str,
    name: str,
    kind: str,
    department: str | None,
    base_url: str | None,
) -> int:
    with sync_pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO source (code, name, kind, department, base_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                kind = EXCLUDED.kind,
                department = EXCLUDED.department,
                base_url = EXCLUDED.base_url
            RETURNING id
            """,
            (code, name, kind, department, base_url),
        ).fetchone()
        assert row is not None
        conn.commit()
        return row[0]


def document_exists(url: str) -> bool:
    with sync_pool.connection() as conn:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM notice WHERE url = %s)",
            (url,),
        ).fetchone()
        return bool(row and row[0])


def document_is_current(url: str) -> bool:
    """현재 파서 버전으로 재수집된 공지인지 확인한다.

    URL만 존재한다고 건너뛰면 본문·첨부 파서를 개선해도 기존 오염
    데이터가 영원히 남는다. 버전이 다른 문서는 다음 수집에서 한 번 재처리한다.
    """
    with sync_pool.connection() as conn:
        row = conn.execute(
            "SELECT extraction_version FROM notice WHERE url = %s",
            (url,),
        ).fetchone()
        return bool(row and row[0] == CURRENT_NOTICE_EXTRACTION_VERSION)


def select_crawl_records(
    source_id: int,
    records: list[dict],
    *,
    recent_days: int = 7,
    refresh_outdated_extraction: bool = False,
) -> list[dict]:
    """URL 상태를 일괄 대조해 상세 처리가 필요한 기록만 반환한다."""
    if not records:
        return []

    from datetime import date, datetime, timedelta

    def parse_date(raw) -> date | None:
        value = str(raw or "").strip().replace(".", "-").replace("/", "-").rstrip("-")
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    unique: dict[str, dict] = {record["url"]: record for record in records}
    urls = list(unique)
    posted_dates = [parse_date(unique[url].get("posted_at")) for url in urls]
    pinned = [bool(unique[url].get("is_pinned")) for url in urls]

    with sync_pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO crawl_url_state (url, source_id, status, posted_at, is_pinned)
            SELECT value.url, %s, 'discovered', value.posted_at, value.is_pinned
            FROM unnest(%s::varchar[], %s::date[], %s::boolean[])
                 AS value(url, posted_at, is_pinned)
            ON CONFLICT (url) DO UPDATE SET
                source_id = EXCLUDED.source_id,
                posted_at = COALESCE(EXCLUDED.posted_at, crawl_url_state.posted_at),
                is_pinned = EXCLUDED.is_pinned,
                last_seen_at = now()
            """,
            (source_id, urls, posted_dates, pinned),
        )
        rows = conn.execute(
            """
            SELECT url, status, extraction_version, posted_at
            FROM crawl_url_state
            WHERE url = ANY(%s)
            """,
            (urls,),
        ).fetchall()
        states = {
            row[0]: {
                "status": row[1],
                "extraction_version": row[2],
                "posted_at": row[3],
            }
            for row in rows
        }
        cutoff = date.today() - timedelta(days=max(0, recent_days))
        selected = [
            unique[url]
            for url in urls
            if (
                states[url]["status"] != "completed"
                or (
                    states[url]["extraction_version"] == CURRENT_NOTICE_EXTRACTION_VERSION
                    and (
                        states[url]["posted_at"] is None
                        or states[url]["posted_at"] >= cutoff
                    )
                )
                or (
                    refresh_outdated_extraction
                    and states[url]["extraction_version"] != CURRENT_NOTICE_EXTRACTION_VERSION
                )
            )
        ]
        if selected:
            conn.execute(
                """
                UPDATE crawl_url_state
                SET last_attempt_at = now(), attempt_count = attempt_count + 1
                WHERE url = ANY(%s)
                """,
                ([record["url"] for record in selected],),
            )
        conn.commit()
    return selected


def mark_crawl_url_completed(url: str, *, posted_at: date | None = None) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            """
            UPDATE crawl_url_state
            SET status = 'completed',
                posted_at = COALESCE(%s, posted_at),
                extraction_version = %s,
                completed_at = now(),
                last_error = NULL
            WHERE url = %s
            """,
            (posted_at, CURRENT_NOTICE_EXTRACTION_VERSION, url),
        )
        conn.commit()


def mark_crawl_url_failed(url: str, error: str) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            """
            UPDATE crawl_url_state
            SET status = 'failed', last_error = %s, last_attempt_at = now()
            WHERE url = %s
            """,
            (error[:4000], url),
        )
        conn.commit()


def upsert_extraction_review(source_id: int, item: dict) -> None:
    """품질 기준 미달 문서를 RAG 적재와 분리해 재검토 가능하게 보존한다."""
    qualities = item.get("extraction_quality") or []
    artifact_path = next(
        (
            asset.get("storage_path")
            for asset in item.get("assets") or []
            if asset.get("storage_path")
        ),
        None,
    )
    with sync_pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO extraction_review
                (source_id, url, title, reason, quality, artifact_path)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                source_id = EXCLUDED.source_id,
                title = EXCLUDED.title,
                reason = EXCLUDED.reason,
                quality = EXCLUDED.quality,
                artifact_path = EXCLUDED.artifact_path,
                updated_at = now()
            """,
            (
                source_id,
                item["url"],
                item.get("title") or "(제목 없음)",
                item.get("review_reason") or "extraction_quality_below_threshold",
                json.dumps(qualities, ensure_ascii=False),
                artifact_path,
            ),
        )
        conn.commit()


def clear_extraction_review(url: str) -> None:
    with sync_pool.connection() as conn:
        conn.execute("DELETE FROM extraction_review WHERE url = %s", (url,))
        conn.commit()


def delete_documents_by_source(source_id: int) -> int:
    with sync_pool.connection() as conn:
        rows = conn.execute(
            "DELETE FROM notice WHERE source_id = %s RETURNING id",
            (source_id,),
        ).fetchall()
        conn.commit()
        return len(rows)


def _replace_periods(conn, notice_id: int, periods: list[Any]) -> None:
    conn.execute("DELETE FROM notice_period WHERE notice_id = %s", (notice_id,))
    for order_idx, raw in enumerate(periods):
        period = _plain(raw)
        if period.get("kind") not in NOTICE_PERIOD_KINDS:
            raise ValueError(f"Unknown notice period kind: {period.get('kind')!r}")
        starts_on = _clean_date(period.get("starts_on"))
        ends_on = _clean_date(period.get("ends_on"))
        if starts_on is None and ends_on is None:
            continue
        conn.execute(
            """
            INSERT INTO notice_period
                (notice_id, kind, starts_on, ends_on, source_text,
                 confidence, inferred_year, order_idx)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                notice_id,
                period["kind"],
                starts_on,
                ends_on,
                str(period.get("source_text") or "").strip(),
                period.get("confidence"),
                bool(period.get("inferred_year")),
                order_idx,
            ),
        )


def _replace_audiences(conn, notice_id: int, audiences: list[Any]) -> None:
    conn.execute("DELETE FROM notice_audience WHERE notice_id = %s", (notice_id,))
    for order_idx, raw in enumerate(audiences):
        audience = _plain(raw)
        if audience.get("kind") not in NOTICE_AUDIENCE_KINDS:
            raise ValueError(f"Unknown notice audience kind: {audience.get('kind')!r}")
        value = str(audience.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            """
            INSERT INTO notice_audience
                (notice_id, kind, value, source_text, confidence, order_idx)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                notice_id,
                audience["kind"],
                value,
                str(audience.get("source_text") or "").strip(),
                audience.get("confidence"),
                order_idx,
            ),
        )


def _replace_application(conn, notice_id: int, value: Any) -> None:
    application = _plain(value)
    conn.execute("DELETE FROM notice_application WHERE notice_id = %s", (notice_id,))
    if not any(
        application.get(key)
        for key in (
            "method",
            "application_url",
            "required_documents",
            "contact",
            "location",
            "benefit",
            "evidence",
        )
    ):
        return
    conn.execute(
        """
        INSERT INTO notice_application
            (notice_id, method, application_url, required_documents,
             contact, location, benefit, evidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            notice_id,
            application.get("method"),
            application.get("application_url"),
            list(application.get("required_documents") or []),
            application.get("contact"),
            application.get("location"),
            application.get("benefit"),
            json.dumps(application.get("evidence") or {}, ensure_ascii=False),
        ),
    )


def insert_document(
    source_id: int,
    url: str,
    title: str,
    content: str,
    category: str,
    summary: str | None = None,
    topics: list[str] | None = None,
    series_key: str | None = None,
    periods: list[Any] | None = None,
    audiences: list[Any] | None = None,
    application: Any = None,
    extraction_confidence: float | None = None,
    extraction_version: str = CURRENT_NOTICE_EXTRACTION_VERSION,
    extra: dict | None = None,
    posted_at=None,
    is_pinned: bool = False,
    preserve_forever: bool = False,
    body_content: str | None = None,
    **_removed_legacy_fields,
) -> int:
    if category not in NOTICE_CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    posted_at = _clean_date(posted_at)
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with sync_pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO notice
                (source_id, url, title, content, body_content, summary,
                 category, topics, series_key, posted_at, is_pinned,
                 preserve_forever, archived_at, archive_reason,
                 content_sha256, extraction_version, extraction_confidence,
                 extra, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, NULL, NULL,
                 %s, %s, %s, %s, now())
            ON CONFLICT (url) DO UPDATE SET
                source_id = EXCLUDED.source_id,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                body_content = EXCLUDED.body_content,
                summary = EXCLUDED.summary,
                category = EXCLUDED.category,
                topics = EXCLUDED.topics,
                series_key = EXCLUDED.series_key,
                posted_at = EXCLUDED.posted_at,
                is_pinned = EXCLUDED.is_pinned,
                preserve_forever = EXCLUDED.preserve_forever,
                archived_at = NULL,
                archive_reason = NULL,
                content_sha256 = EXCLUDED.content_sha256,
                extraction_version = EXCLUDED.extraction_version,
                extraction_confidence = EXCLUDED.extraction_confidence,
                extra = EXCLUDED.extra,
                updated_at = now()
            RETURNING id
            """,
            (
                source_id,
                url,
                title,
                content,
                body_content or content,
                summary,
                category,
                list(topics or []),
                series_key,
                posted_at,
                is_pinned,
                preserve_forever,
                content_sha256,
                extraction_version,
                extraction_confidence,
                json.dumps(extra, ensure_ascii=False) if extra else None,
            ),
        ).fetchone()
        assert row is not None
        notice_id = row[0]
        _replace_periods(conn, notice_id, periods or [])
        _replace_audiences(conn, notice_id, audiences or [])
        _replace_application(conn, notice_id, application)
        conn.commit()
    print(f"✅ [{title}] notice 저장 완료 (id={notice_id})")
    return notice_id


def insert_assets(notice_id: int, assets: list[dict]) -> None:
    with sync_pool.connection() as conn:
        conn.execute("DELETE FROM notice_asset WHERE notice_id = %s", (notice_id,))
        for asset in assets:
            conn.execute(
                """
                INSERT INTO notice_asset
                    (notice_id, kind, filename, source_url, storage_path,
                     mime_type, extracted_text, order_idx, extra)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    notice_id,
                    asset["kind"],
                    asset.get("filename"),
                    asset["source_url"],
                    asset.get("storage_path"),
                    asset.get("mime_type"),
                    asset.get("extracted_text", ""),
                    asset.get("order_idx", 0),
                    json.dumps(asset.get("extra") or {}, ensure_ascii=False),
                ),
            )
        conn.commit()
    if assets:
        print(f"  ↳ asset {len(assets)}건 저장 완료")


def insert_chunks(notice_id: int, chunks: list[tuple]) -> None:
    with sync_pool.connection() as conn:
        conn.execute("DELETE FROM notice_chunk WHERE notice_id = %s", (notice_id,))
        for chunk in chunks:
            if len(chunk) == 3:
                idx, content, vector = chunk
                chunk_type = "body"
                attachment_name = None
            else:
                idx, content, vector, chunk_type, attachment_name = chunk
            conn.execute(
                """
                INSERT INTO notice_chunk
                    (notice_id, chunk_idx, content, chunk_type,
                     attachment_name, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    notice_id,
                    idx,
                    content,
                    chunk_type,
                    attachment_name,
                    vector,
                ),
            )
        conn.commit()
    if chunks:
        print(f"  ↳ chunk {len(chunks)}건 저장 완료")


_SEARCH_SELECT = """
    n.url,
    n.title,
    nc.content,
    1 - (nc.embedding <=> %s::vector) AS score,
    n.posted_at,
    period.starts_on,
    period.ends_on,
    n.category,
    audience.targets,
    n.topics,
    s.code,
    s.name,
    s.kind,
    s.department,
    n.summary,
    n.body_content,
    asset.names,
    asset.figures
"""

_SEARCH_JOINS = """
    FROM notice_chunk nc
    JOIN notice n ON n.id = nc.notice_id
    JOIN source s ON s.id = n.source_id
    LEFT JOIN LATERAL (
        SELECT min(starts_on) AS starts_on, max(ends_on) AS ends_on
        FROM notice_period
        WHERE notice_id = n.id AND kind = 'application'
    ) period ON true
    LEFT JOIN LATERAL (
        SELECT array_agg(value ORDER BY order_idx) AS targets
        FROM notice_audience
        WHERE notice_id = n.id
          AND kind IN ('grade', 'enrollment_status')
    ) audience ON true
    LEFT JOIN LATERAL (
        SELECT array_agg(filename ORDER BY order_idx)
               FILTER (
                   WHERE filename IS NOT NULL
                     AND kind NOT IN (
                         'attachment_hwp_structure','attachment_hwp_markdown',
                         'attachment_hwp_validation','attachment_hwp_image',
                         'attachment_document_image',
                         'attachment_hwp_binary','inline_image'
                     )
               ) AS names,
               jsonb_agg(
                   jsonb_build_object(
                       'asset_id', id,
                       'number', (extra->'figure'->>'number')::int,
                       'label', extra->'figure'->>'label',
                       'marker', extra->'figure'->>'marker',
                       'scope', extra->'figure'->>'scope',
                       'filename', filename,
                       'description', extra->'analysis'->>'description',
                       'context', extra->'figure'->>'context',
                       'url', '/api/notice-assets/' || id || '/content'
                   ) ORDER BY (extra->'figure'->>'number')::int
               ) FILTER (
                   WHERE kind IN ('attachment_hwp_image','attachment_document_image','inline_image')
                     AND extra->'figure'->>'number' IS NOT NULL
                     AND (
                         nc.attachment_name IS NULL
                         OR extra->>'parentAttachment' IS NULL
                         OR nc.attachment_name LIKE (extra->>'parentAttachment') || '%%'
                     )
                     AND COALESCE(extra->'analysis'->>'contextMatch','uncertain') <> 'unrelated'
               ) AS figures
        FROM notice_asset
        WHERE notice_id = n.id
    ) asset ON true
"""


def search_chunks(
    query_embedding: list[float],
    major: str | None = None,
    categories: list[str] | None = None,
    limit: int = 10,
    distinct_by_doc: bool = False,
    time_scope: str = "current",
    year: int | None = None,
    notice_ids: list[int] | None = None,
):
    conditions: list[str] = []
    params: list[Any] = [query_embedding]

    if time_scope == "current":
        conditions.append("n.archived_at IS NULL")
    elif time_scope == "historical":
        conditions.append("n.archived_at IS NOT NULL")
    elif time_scope != "all":
        raise ValueError(f"Unknown time scope: {time_scope!r}")
    if categories:
        conditions.append("n.category = ANY(%s)")
        params.append(categories)
    if major:
        conditions.append(
            """
            (s.department = %s OR s.department = '공통' OR s.department IS NULL)
            AND (
                NOT EXISTS (
                    SELECT 1 FROM notice_audience ad
                    WHERE ad.notice_id = n.id AND ad.kind = 'department'
                )
                OR EXISTS (
                    SELECT 1 FROM notice_audience ad
                    WHERE ad.notice_id = n.id
                      AND ad.kind = 'department'
                      AND ad.value = %s
                )
            )
            """
        )
        params.extend([major, major])
    if year is not None:
        if year < 2000 or year > 2200:
            raise ValueError("year must be between 2000 and 2200")
        conditions.append("n.posted_at >= %s AND n.posted_at < %s")
        params.extend([date(year, 1, 1), date(year + 1, 1, 1)])
    if notice_ids:
        conditions.append("n.id = ANY(%s)")
        params.append(notice_ids)

    where = " AND ".join(conditions) if conditions else "true"
    if distinct_by_doc:
        query = f"""
            WITH candidates AS (
                SELECT {_SEARCH_SELECT},
                       row_number() OVER (
                           PARTITION BY n.id
                           ORDER BY nc.embedding <=> %s::vector
                       ) AS document_rank
                {_SEARCH_JOINS}
                WHERE {where}
            )
            SELECT url, title, content, score, posted_at, starts_on, ends_on,
                   category, targets, topics, code, name, kind, department,
                   summary, body_content, names, figures
            FROM candidates
            WHERE document_rank = 1
            ORDER BY score DESC
            LIMIT %s
        """
        params.insert(1, query_embedding)
    else:
        query = f"""
            SELECT {_SEARCH_SELECT}
            {_SEARCH_JOINS}
            WHERE {where}
            ORDER BY nc.embedding <=> %s::vector
            LIMIT %s
        """
        params.append(query_embedding)
    params.append(limit)

    with sync_pool.connection() as conn:
        return conn.execute(query, params).fetchall()


def get_document_content(url: str, category: str | None = None) -> str | None:
    conditions = ["url = %s"]
    params: list[Any] = [url]
    if category:
        conditions.append("category = %s")
        params.append(category)
    with sync_pool.connection() as conn:
        row = conn.execute(
            f"SELECT content FROM notice WHERE {' AND '.join(conditions)}",
            params,
        ).fetchone()
        return row[0] if row else None


def get_documents(
    category: str | None = None,
    major: str | None = None,
    kind: str | None = None,
    department: str | None = None,
    limit: int = 30,
    cursor_ts=None,
    cursor_url: str | None = None,
    exclude_codes=None,
    time_scope: str = "current",
):
    conditions: list[str] = []
    params: list[Any] = []
    if time_scope == "current":
        conditions.append("n.archived_at IS NULL")
    elif time_scope == "historical":
        conditions.append("n.archived_at IS NOT NULL")
    elif time_scope != "all":
        raise ValueError(f"Unknown time scope: {time_scope!r}")
    if category:
        conditions.append("n.category = %s")
        params.append(category)
    if major:
        conditions.append(
            "(s.department = %s OR s.department = '공통' OR s.department IS NULL)"
        )
        params.append(major)
    if kind:
        conditions.append("s.kind = %s")
        params.append(kind)
    if department:
        conditions.append("s.department = %s")
        params.append(department)
    if cursor_ts is not None and cursor_url is not None:
        conditions.append(
            "(COALESCE(n.posted_at::timestamp, n.crawled_at), n.url) < (%s, %s)"
        )
        params.extend([cursor_ts, cursor_url])
    if exclude_codes:
        conditions.append("s.code <> ALL(%s)")
        params.append(list(exclude_codes))

    where = " AND ".join(conditions) if conditions else "true"
    query = f"""
        SELECT
            n.url, n.title, n.content, n.posted_at,
            period.starts_on, period.ends_on, n.category,
            audience.targets, n.topics,
            s.code, s.name, s.kind, s.department, n.summary,
            COALESCE(n.posted_at::timestamp, n.crawled_at) AS sort_ts
        FROM notice n
        JOIN source s ON s.id = n.source_id
        LEFT JOIN LATERAL (
            SELECT min(starts_on) AS starts_on, max(ends_on) AS ends_on
            FROM notice_period
            WHERE notice_id = n.id AND kind = 'application'
        ) period ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(value ORDER BY order_idx) AS targets
            FROM notice_audience
            WHERE notice_id = n.id
              AND kind IN ('grade', 'enrollment_status')
        ) audience ON true
        WHERE {where}
        ORDER BY sort_ts DESC NULLS LAST, n.url DESC
        LIMIT %s
    """
    params.append(limit)
    with sync_pool.connection() as conn:
        return conn.execute(query, params).fetchall()


def list_notices_for_scan(
    category: str | None = None,
    status: str = "any",
    as_of: date | None = None,
    time_scope: str = "current",
    department: str | None = None,
    grade: int | None = None,
    year: int | None = None,
    topic: str | None = None,
    sort: str = "posted_at",
    offset: int = 0,
    page_size: int = 30,
) -> dict:
    """구조화 메타데이터로 공지를 필터·집계한다. 임베딩은 사용하지 않는다."""
    as_of = as_of or date.today()
    if category is not None and category not in NOTICE_CATEGORIES:
        raise ValueError(f"Unknown category: {category!r}")
    if status not in {"any", "open", "upcoming", "closed"}:
        raise ValueError(f"Unknown notice status: {status!r}")
    if time_scope not in {"current", "historical", "all"}:
        raise ValueError(f"Unknown time scope: {time_scope!r}")
    if sort not in {"posted_at", "start_date", "end_date"}:
        raise ValueError(f"Unknown scan sort: {sort!r}")
    if grade is not None and grade not in {1, 2, 3, 4}:
        raise ValueError("grade must be between 1 and 4")
    if year is not None and (year < 2000 or year > 2200):
        raise ValueError("year must be between 2000 and 2200")
    offset = max(0, int(offset))
    page_size = max(1, min(int(page_size), 50))

    conditions: list[str] = []
    params: list[Any] = []
    if time_scope == "current":
        conditions.append("n.archived_at IS NULL")
    elif time_scope == "historical":
        conditions.append("n.archived_at IS NOT NULL")
    if category:
        conditions.append("n.category = %s")
        params.append(category)
    if status == "open":
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM notice_period p
                WHERE p.notice_id = n.id
                  AND p.kind = 'application'
                  AND (p.starts_on IS NULL OR p.starts_on <= %s)
                  AND (p.ends_on IS NULL OR p.ends_on >= %s)
            )
            """
        )
        params.extend([as_of, as_of])
    elif status == "upcoming":
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM notice_period p
                WHERE p.notice_id = n.id
                  AND p.kind = 'application'
                  AND p.starts_on > %s
            )
            """
        )
        params.append(as_of)
    elif status == "closed":
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM notice_period p
                WHERE p.notice_id = n.id
                  AND p.kind = 'application'
                  AND p.ends_on < %s
            )
            """
        )
        params.append(as_of)
    if department:
        conditions.append(
            """
            (s.department = %s OR s.department = '공통' OR s.department IS NULL)
            AND (
                NOT EXISTS (
                    SELECT 1 FROM notice_audience ad
                    WHERE ad.notice_id = n.id AND ad.kind = 'department'
                )
                OR EXISTS (
                    SELECT 1 FROM notice_audience ad
                    WHERE ad.notice_id = n.id
                      AND ad.kind = 'department'
                      AND ad.value = %s
                )
            )
            """
        )
        params.extend([department, department])
    if grade:
        conditions.append(
            """
            (
                NOT EXISTS (
                    SELECT 1 FROM notice_audience ag
                    WHERE ag.notice_id = n.id AND ag.kind = 'grade'
                )
                OR EXISTS (
                    SELECT 1 FROM notice_audience ag
                    WHERE ag.notice_id = n.id
                      AND ag.kind = 'grade'
                      AND ag.value IN (%s, %s)
                )
            )
            """
        )
        params.extend([f"{grade}학년", str(grade)])
    if year:
        conditions.append("n.posted_at >= %s AND n.posted_at < %s")
        params.extend([date(year, 1, 1), date(year + 1, 1, 1)])
    if topic:
        conditions.append(
            "(%s = ANY(n.topics) OR n.title ILIKE %s OR COALESCE(n.summary, '') ILIKE %s)"
        )
        params.extend([topic, f"%{topic}%", f"%{topic}%"])

    where = " AND ".join(conditions) if conditions else "true"
    order_by = {
        "posted_at": "n.posted_at DESC NULLS LAST, n.id DESC",
        "start_date": "period.starts_on ASC NULLS LAST, n.posted_at DESC NULLS LAST",
        "end_date": "period.ends_on ASC NULLS LAST, n.posted_at DESC NULLS LAST",
    }[sort]
    base_from = f"""
        FROM notice n
        JOIN source s ON s.id = n.source_id
        LEFT JOIN LATERAL (
            SELECT min(starts_on) AS starts_on, max(ends_on) AS ends_on
            FROM notice_period
            WHERE notice_id = n.id AND kind = 'application'
        ) period ON true
        WHERE {where}
    """

    with sync_pool.connection() as conn:
        total = conn.execute(
            f"SELECT count(*) {base_from}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT
                n.id, n.url, n.title, n.summary, n.category, n.topics,
                n.series_key, n.posted_at, n.archived_at,
                period.starts_on, period.ends_on,
                s.code, s.name, s.department,
                COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'kind', p.kind,
                                'starts_on', p.starts_on,
                                'ends_on', p.ends_on,
                                'source_text', p.source_text,
                                'confidence', p.confidence,
                                'inferred_year', p.inferred_year
                            )
                            ORDER BY p.order_idx
                        )
                        FROM notice_period p
                        WHERE p.notice_id = n.id
                    ),
                    '[]'::jsonb
                ) AS periods,
                COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'kind', a.kind,
                                'value', a.value,
                                'source_text', a.source_text,
                                'confidence', a.confidence
                            )
                            ORDER BY a.order_idx
                        )
                        FROM notice_audience a
                        WHERE a.notice_id = n.id
                    ),
                    '[]'::jsonb
                ) AS audiences
            {base_from}
            ORDER BY {order_by}
            OFFSET %s
            LIMIT %s
            """,
            [*params, offset, page_size],
        ).fetchall()

    items = []
    for row in rows:
        items.append(
            {
                "id": row[0],
                "url": row[1],
                "title": row[2],
                "summary": row[3],
                "category": row[4],
                "topics": list(row[5] or []),
                "series_key": row[6],
                "posted_at": row[7].isoformat() if row[7] else None,
                "archived": row[8] is not None,
                "application_start": row[9].isoformat() if row[9] else None,
                "application_end": row[10].isoformat() if row[10] else None,
                "source_code": row[11],
                "source_name": row[12],
                "department": row[13],
                "periods": list(row[14] or []),
                "audiences": list(row[15] or []),
            }
        )
    return {
        "total": int(total),
        "offset": offset,
        "returned": len(items),
        "as_of": as_of.isoformat(),
        "time_scope": time_scope,
        "status": status,
        "items": items,
    }


__all__ = [
    "archive_documents",
    "sync_pinned_urls",
    "upsert_source",
    "document_exists",
    "document_is_current",
    "select_crawl_records",
    "mark_crawl_url_completed",
    "mark_crawl_url_failed",
    "CURRENT_NOTICE_EXTRACTION_VERSION",
    "delete_documents_by_source",
    "insert_document",
    "insert_assets",
    "insert_chunks",
    "search_chunks",
    "get_document_content",
    "get_documents",
    "list_notices_for_scan",
]
