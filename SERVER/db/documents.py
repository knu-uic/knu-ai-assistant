from __future__ import annotations

import json
from datetime import date

import psycopg
from psycopg import sql

from db.schema import (
    DB_URL,
    SLUGS,
    SLUG_TO_CATEGORY,
    _chunk_ident,
    _connect_with_vector,
    _doc_ident,
    _months_ago,
    _slug,
)


def prune_documents(
    retention_months: int = 6,
    delete_expired: bool = True,
    protected_urls: set[str] | None = None,
) -> int:
    today = date.today()
    cutoff = _months_ago(today, retention_months)
    protected_urls = protected_urls or set()
    total = 0

    with psycopg.connect(DB_URL) as conn:
        for slug in SLUGS:
            category = SLUG_TO_CATEGORY[slug]
            expired_clause = (
                sql.SQL(" OR (end_date IS NOT NULL AND end_date < %s)")
                if delete_expired
                else sql.SQL("")
            )
            query = sql.SQL("""
                DELETE FROM {doc}
                WHERE NOT is_pinned
                  AND NOT (url = ANY(%s))
                  AND (
                    COALESCE(posted_at, crawled_at::date) < %s
                    {expired}
                  )
                RETURNING id;
            """).format(doc=_doc_ident(slug), expired=expired_clause)
            params = [list(protected_urls), cutoff]
            if delete_expired:
                params.append(today)

            deleted_ids = [row[0] for row in conn.execute(query, params).fetchall()]
            if not deleted_ids:
                continue

            conn.execute(
                "DELETE FROM document_asset WHERE category = %s AND document_id = ANY(%s);",
                (category, deleted_ids),
            )
            total += len(deleted_ids)
            print(f"  ↳ 오래된/마감 문서 정리: {category} {len(deleted_ids)}건")

        conn.commit()

    if total:
        print(f"🧹 문서 정리 완료: {total}건 삭제 (보존 {retention_months}개월, 마감문서 삭제={delete_expired}, 보호 URL {len(protected_urls)}건)")
    else:
        print(f"🧹 문서 정리 대상 없음 (보존 {retention_months}개월, 마감문서 삭제={delete_expired}, 보호 URL {len(protected_urls)}건)")
    return total


def sync_pinned_urls(pinned_urls: set[str]) -> None:
    with psycopg.connect(DB_URL) as conn:
        for slug in SLUGS:
            conn.execute(
                sql.SQL("UPDATE {doc} SET is_pinned = false WHERE is_pinned = true;").format(
                    doc=_doc_ident(slug),
                )
            )
            if pinned_urls:
                conn.execute(
                    sql.SQL("UPDATE {doc} SET is_pinned = true WHERE url = ANY(%s);").format(
                        doc=_doc_ident(slug),
                    ),
                    (list(pinned_urls),),
                )
        conn.commit()
    print(f"📌 고정 공지 동기화 완료: 현재 고정 URL {len(pinned_urls)}건")


def upsert_source(code: str, name: str, kind: str, department: str | None, base_url: str | None) -> int:
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute("""
            INSERT INTO source (code, name, kind, department, base_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                kind = EXCLUDED.kind,
                department = EXCLUDED.department,
                base_url = EXCLUDED.base_url
            RETURNING id;
        """, (code, name, kind, department, base_url))
        row = cur.fetchone()
        assert row is not None
        source_id = row[0]
        conn.commit()
        return source_id


def document_exists(url: str) -> bool:
    sub = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT 1 FROM {} WHERE url = %s").format(_doc_ident(s)) for s in SLUGS
    )
    query = sql.SQL("SELECT EXISTS({sub});").format(sub=sub)
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(query, tuple([url] * len(SLUGS)))
        row = cur.fetchone()
        return bool(row and row[0])


def delete_documents_by_source(source_id: int) -> int:
    deleted_total = 0
    with psycopg.connect(DB_URL) as conn:
        for slug in SLUGS:
            category = SLUG_TO_CATEGORY[slug]
            rows = conn.execute(
                sql.SQL(
                    """
                    DELETE FROM {doc}
                    WHERE source_id = %s
                    RETURNING id;
                    """
                ).format(doc=_doc_ident(slug)),
                (source_id,),
            ).fetchall()

            if not rows:
                continue

            deleted_ids = [row[0] for row in rows]
            conn.execute(
                """
                DELETE FROM document_asset
                WHERE category = %s
                  AND document_id = ANY(%s);
                """,
                (category, deleted_ids),
            )
            deleted_total += len(deleted_ids)

        conn.commit()
    return deleted_total


def insert_document(
    source_id: int,
    url: str,
    title: str,
    content: str,
    start_date,
    end_date,
    category: str,
    target,
    keywords,
    summary: str | None = None,
    extra: dict | None = None,
    posted_at=None,
    is_pinned: bool = False,
    body_content: str | None = None,
    attachment_names: list[str] | None = None,
    attachment_contents: list[dict] | None = None,
) -> int:
    slug = _slug(category)

    if not start_date or str(start_date).strip() == "":
        start_date = None
    if not end_date or str(end_date).strip() == "":
        end_date = None
    if not posted_at or str(posted_at).strip() == "":
        posted_at = None

    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    attachment_names_json = json.dumps(attachment_names or [], ensure_ascii=False)
    attachment_contents_json = json.dumps(attachment_contents or [], ensure_ascii=False)

    query = sql.SQL("""
        INSERT INTO {doc}
            (
                source_id,
                url,
                title,
                content,
                body_content,
                attachment_names,
                attachment_contents,
                summary,
                posted_at,
                start_date,
                end_date,
                is_pinned,
                target,
                keywords,
                extra,
                updated_at
            )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            now()
        )
        ON CONFLICT (url) DO UPDATE SET
            source_id = EXCLUDED.source_id,
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            body_content = EXCLUDED.body_content,
            attachment_names = EXCLUDED.attachment_names,
            attachment_contents = EXCLUDED.attachment_contents,
            summary = EXCLUDED.summary,
            posted_at = EXCLUDED.posted_at,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            is_pinned = EXCLUDED.is_pinned,
            target = EXCLUDED.target,
            keywords = EXCLUDED.keywords,
            extra = EXCLUDED.extra,
            updated_at = now()
        RETURNING id;
    """).format(doc=_doc_ident(slug))

    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            query,
            (
                source_id,
                url,
                title,
                content,
                body_content or content,
                attachment_names_json,
                attachment_contents_json,
                summary,
                posted_at,
                start_date,
                end_date,
                is_pinned,
                target,
                keywords,
                extra_json,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        document_id = row[0]
        conn.commit()
        print(f"✅ [{title}] document_{slug} 저장 완료 (id={document_id})")
        return document_id


def insert_assets(category: str, document_id: int, assets: list[dict]):
    if not assets:
        return
    _slug(category)
    with psycopg.connect(DB_URL) as conn:
        conn.execute(
            "DELETE FROM document_asset WHERE category = %s AND document_id = %s;",
            (category, document_id),
        )
        for a in assets:
            conn.execute(
                """
                INSERT INTO document_asset
                    (category, document_id, kind, filename, source_url, storage_path,
                     mime_type, extracted_text, order_idx)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    category,
                    document_id,
                    a["kind"],
                    a.get("filename"),
                    a["source_url"],
                    a.get("storage_path"),
                    a.get("mime_type"),
                    a.get("extracted_text", ""),
                    a.get("order_idx", 0),
                ),
            )
        conn.commit()
        print(f"  ↳ asset {len(assets)}건 저장 완료")


def insert_chunks(
    category: str,
    document_id: int,
    chunks: list[tuple],
):
    if not chunks:
        return

    slug = _slug(category)
    del_q = sql.SQL("DELETE FROM {} WHERE document_id = %s;").format(_chunk_ident(slug))
    ins_q = sql.SQL(
        """
        INSERT INTO {}
        (
            document_id,
            chunk_idx,
            content,
            chunk_type,
            attachment_name,
            embedding
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """
    ).format(_chunk_ident(slug))

    with _connect_with_vector() as conn:
        conn.execute(del_q, (document_id,))
        for chunk in chunks:
            if len(chunk) == 3:
                idx, content, vector = chunk
                chunk_type = "body"
                attachment_name = None
            else:
                idx, content, vector, chunk_type, attachment_name = chunk
            conn.execute(
                ins_q,
                (
                    document_id,
                    idx,
                    content,
                    chunk_type,
                    attachment_name,
                    vector,
                ),
            )
        conn.commit()
        print(f"  ↳ chunk {len(chunks)}건 저장 완료 (→ document_{slug}_chunk)")


def _search_subquery(slug: str, major_filter: bool, distinct_by_doc: bool = False) -> tuple[sql.Composable, list]:
    category_literal = SLUG_TO_CATEGORY[slug]
    where_clause = (
        sql.SQL(" WHERE (s.department = %s OR s.department = '공통' OR s.department IS NULL) ")
        if major_filter
        else sql.SQL(" ")
    )
    select_prefix = sql.SQL("SELECT DISTINCT ON (d.url)") if distinct_by_doc else sql.SQL("SELECT")
    order_by = (
        sql.SQL(" ORDER BY d.url, c.embedding <=> %s::vector ")
        if distinct_by_doc
        else sql.SQL(" ORDER BY c.embedding <=> %s::vector ")
    )

    sub = sql.SQL("""
        {select_prefix}
               d.url,
               d.title,
               c.content,
               1 - (c.embedding <=> %s::vector) AS score,
               d.posted_at,
               d.start_date,
               d.end_date,
               {cat_lit}::text AS category,
               d.target,
               d.keywords,
               s.code,
               s.name,
               s.kind,
               s.department,
               d.summary,
               d.body_content,
               d.attachment_names
        FROM {chunk} c
        JOIN {doc} d ON d.id = c.document_id
        JOIN source s ON s.id = d.source_id
        {where}
        {order_by}
    """).format(
        select_prefix=select_prefix,
        cat_lit=sql.Literal(category_literal),
        chunk=_chunk_ident(slug),
        doc=_doc_ident(slug),
        where=where_clause,
        order_by=order_by,
    )

    return sub, [category_literal]


def search_chunks(
    query_embedding: list[float],
    major: str | None = None,
    categories: list[str] | None = None,
    limit: int = 10,
    distinct_by_doc: bool = False,
):
    target_slugs = [_slug(c) for c in categories] if categories else list(SLUGS)
    subs: list[sql.Composable] = []
    params: list = []
    for slug in target_slugs:
        sub, _ = _search_subquery(slug, major_filter=bool(major), distinct_by_doc=distinct_by_doc)
        subs.append(sql.SQL("(") + sub + sql.SQL(")"))
        params.append(query_embedding)
        if major:
            params.append(major)
        params.append(query_embedding)

    union = sql.SQL(" UNION ALL ").join(subs)
    final_q = sql.SQL("""
        SELECT url, title, content, score, posted_at, start_date, end_date,
               category, target, keywords,
               code, name, kind, department,
               summary,
               body_content,
               attachment_names
        FROM ({union}) merged
        ORDER BY score DESC
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with _connect_with_vector() as conn:
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()


def get_document_content(category: str, url: str) -> str | None:
    slug = _slug(category)
    q = sql.SQL("SELECT content FROM {doc} WHERE url = %s").format(doc=_doc_ident(slug))
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(q, (url,))
        row = cur.fetchone()
        return row[0] if row else None


def _list_subquery(slug: str, where: sql.Composable) -> sql.Composable:
    return sql.SQL("""
        SELECT d.url, d.title, d.content, d.posted_at, d.start_date, d.end_date,
               {cat_lit}::text AS category,
               d.target, d.keywords,
               s.code, s.name, s.kind, s.department,
               d.crawled_at,
               d.summary
        FROM {doc} d
        JOIN source s ON s.id = d.source_id
        {where}
    """).format(
        cat_lit=sql.Literal(SLUG_TO_CATEGORY[slug]),
        doc=_doc_ident(slug),
        where=where,
    )


def get_documents(
    category: str | None = None,
    major: str | None = None,
    kind: str | None = None,
    department: str | None = None,
    limit: int = 30,
):
    target_slugs = [_slug(category)] if category else list(SLUGS)

    conditions: list[sql.Composable] = []
    base_params: list = []
    if major:
        conditions.append(sql.SQL("(s.department = %s OR s.department = '공통' OR s.department IS NULL)"))
        base_params.append(major)
    if kind:
        conditions.append(sql.SQL("s.kind = %s"))
        base_params.append(kind)
    if department:
        conditions.append(sql.SQL("s.department = %s"))
        base_params.append(department)
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")

    subs = [sql.SQL("(") + _list_subquery(slug, where) + sql.SQL(")") for slug in target_slugs]
    params: list = []
    for _ in target_slugs:
        params.extend(base_params)

    union = sql.SQL(" UNION ALL ").join(subs)
    final_q = sql.SQL("""
        SELECT url, title, content, posted_at, start_date, end_date,
               category, target, keywords,
               code, name, kind, department, summary
        FROM ({union}) merged
        ORDER BY COALESCE(posted_at::timestamp, crawled_at) DESC NULLS LAST
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with psycopg.connect(DB_URL) as conn:
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()


__all__ = [
    "prune_documents",
    "sync_pinned_urls",
    "upsert_source",
    "document_exists",
    "delete_documents_by_source",
    "insert_document",
    "insert_assets",
    "insert_chunks",
    "search_chunks",
    "get_document_content",
    "get_documents",
]
