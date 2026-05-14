import json
import os
import psycopg
from psycopg import sql
from pgvector.psycopg import register_vector
from dotenv import load_dotenv

load_dotenv()
DB_URL = f"postgresql://knu-uic:{os.getenv("DB_PASSWORD")}@db:5432/knu-uic"


# schema.py의 category Literal과 1:1 매핑 — SQL 식별자에 한글/슬래시 못 쓰므로 영문 슬러그로 변환.
CATEGORY_SLUGS: dict[str, str] = {
    "장학/등록": "scholarship",
    "학사/수업": "academic",
    "진로/취업": "career",
    "행사/공모전": "event",
    "일반/기타": "etc",
}
SLUG_TO_CATEGORY: dict[str, str] = {v: k for k, v in CATEGORY_SLUGS.items()}
SLUGS: list[str] = list(CATEGORY_SLUGS.values())


def _slug(category: str) -> str:
    s = CATEGORY_SLUGS.get(category)
    if not s:
        raise ValueError(f"Unknown category: {category!r}")
    return s


def _doc_ident(slug: str) -> sql.Identifier:
    return sql.Identifier(f"document_{slug}")


def _chunk_ident(slug: str) -> sql.Identifier:
    return sql.Identifier(f"document_{slug}_chunk")


def _connect_with_vector():
    """pgvector 어댑터가 등록된 커넥션을 돌려준다 (vector 컬럼 쓰는 쿼리 전용)."""
    conn = psycopg.connect(DB_URL)
    register_vector(conn)
    return conn


def init_db():
    """category별 document/chunk 물리 분리 스키마 생성. 기존 단일 document 잔재는 DROP."""
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # 이전 스키마(단일 document) 잔재 제거
        for legacy in ("notice_asset", "notice", "document_chunk", "document_asset", "document"):
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(sql.Identifier(legacy)))
        for slug in SLUGS:
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(_chunk_ident(slug)))
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE;").format(_doc_ident(slug)))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS source (
                id BIGSERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                kind VARCHAR(20) NOT NULL CHECK (kind IN ('notice', 'academic')),
                department VARCHAR(100),
                base_url VARCHAR(500),
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)

        for slug in SLUGS:
            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {doc} (
                    id BIGSERIAL PRIMARY KEY,
                    source_id BIGINT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
                    url VARCHAR(500) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    start_date DATE,
                    end_date DATE,
                    target VARCHAR(100)[],
                    keywords VARCHAR(50)[],
                    extra JSONB,
                    crawled_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now()
                );
            """).format(doc=_doc_ident(slug)))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(source_id);").format(
                idx=sql.Identifier(f"idx_document_{slug}_source"),
                doc=_doc_ident(slug),
            ))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(end_date);").format(
                idx=sql.Identifier(f"idx_document_{slug}_end_date"),
                doc=_doc_ident(slug),
            ))

            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {chunk} (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES {doc}(id) ON DELETE CASCADE,
                    chunk_idx INT NOT NULL,
                    content TEXT NOT NULL,
                    source_asset_id BIGINT,
                    embedding vector(768) NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(document_id, chunk_idx)
                );
            """).format(chunk=_chunk_ident(slug), doc=_doc_ident(slug)))
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {chunk}(document_id);").format(
                idx=sql.Identifier(f"idx_document_{slug}_chunk_document"),
                chunk=_chunk_ident(slug),
            ))
            conn.execute(sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON {chunk} USING hnsw (embedding vector_cosine_ops);"
            ).format(
                idx=sql.Identifier(f"idx_document_{slug}_chunk_embedding"),
                chunk=_chunk_ident(slug),
            ))

        # asset은 검색 경로가 아니라 부속 데이터 — 통합 유지하되 (category, document_id)로 식별.
        # FK는 5개 테이블에 걸 수 없어 application-level cascade.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS document_asset (
                id BIGSERIAL PRIMARY KEY,
                category VARCHAR(20) NOT NULL,
                document_id BIGINT NOT NULL,
                kind VARCHAR(30) NOT NULL,
                filename VARCHAR(300),
                source_url VARCHAR(800) NOT NULL,
                storage_path VARCHAR(800),
                mime_type VARCHAR(80),
                extracted_text TEXT,
                order_idx INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_asset_doc  ON document_asset(category, document_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_document_asset_kind ON document_asset(kind);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                student_id VARCHAR(20) PRIMARY KEY,
                major VARCHAR(50),
                name VARCHAR(50),
                interests TEXT,
                courses TEXT
            );
        """)
        conn.commit()
        print(f"✅ source + {len(SLUGS)}개 category 테이블({', '.join(SLUGS)}) + asset/users 생성 완료")


def upsert_source(code: str, name: str, kind: str, department: str | None, base_url: str | None) -> int:
    """source 테이블에 UPSERT 후 id 반환."""
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
    """5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단."""
    # EXISTS가 첫 행에서 short-circuit하므로 LIMIT 불필요. LIMIT을 넣으면 UNION ALL 문법 충돌.
    sub = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT 1 FROM {} WHERE url = %s").format(_doc_ident(s)) for s in SLUGS
    )
    query = sql.SQL("SELECT EXISTS({sub});").format(sub=sub)
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(query, tuple([url] * len(SLUGS)))
        row = cur.fetchone()
        return bool(row and row[0])


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
    extra: dict | None = None,
) -> int:
    """category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환."""
    slug = _slug(category)

    if not start_date or str(start_date).strip() == "":
        start_date = None
    if not end_date or str(end_date).strip() == "":
        end_date = None

    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None

    query = sql.SQL("""
        INSERT INTO {doc}
            (source_id, url, title, content, start_date, end_date,
             target, keywords, extra, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (url) DO UPDATE SET
            source_id = EXCLUDED.source_id,
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            target = EXCLUDED.target,
            keywords = EXCLUDED.keywords,
            extra = EXCLUDED.extra,
            updated_at = now()
        RETURNING id;
    """).format(doc=_doc_ident(slug))

    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(query, (source_id, url, title, content, start_date, end_date,
                                   target, keywords, extra_json))
        row = cur.fetchone()
        assert row is not None
        document_id = row[0]
        conn.commit()
        print(f"✅ [{title}] document_{slug} 저장 완료 (id={document_id})")
        return document_id


def insert_assets(category: str, document_id: int, assets: list[dict]):
    """document_asset(통합)에 일괄 저장. (category, document_id) 키로 기존 자산 삭제 후 재삽입."""
    if not assets:
        return
    _slug(category)  # 유효성 검증만

    with psycopg.connect(DB_URL) as conn:
        conn.execute(
            "DELETE FROM document_asset WHERE category = %s AND document_id = %s;",
            (category, document_id),
        )
        for a in assets:
            conn.execute("""
                INSERT INTO document_asset
                    (category, document_id, kind, filename, source_url, storage_path,
                     mime_type, extracted_text, order_idx)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                category,
                document_id,
                a["kind"],
                a.get("filename"),
                a["source_url"],
                a.get("storage_path"),
                a.get("mime_type"),
                a.get("extracted_text", ""),
                a.get("order_idx", 0),
            ))
        conn.commit()
        print(f"  ↳ asset {len(assets)}건 저장 완료")


def insert_chunks(category: str, document_id: int, chunks: list[tuple[int, str, list[float]]]):
    """category에 해당하는 document_{slug}_chunk에 일괄 저장.

    chunks: [(chunk_idx, content, embedding_vector), ...]
    """
    if not chunks:
        return
    slug = _slug(category)

    del_q = sql.SQL("DELETE FROM {} WHERE document_id = %s;").format(_chunk_ident(slug))
    ins_q = sql.SQL(
        "INSERT INTO {} (document_id, chunk_idx, content, embedding) VALUES (%s, %s, %s, %s)"
    ).format(_chunk_ident(slug))

    with _connect_with_vector() as conn:
        conn.execute(del_q, (document_id,))
        for idx, content, vector in chunks:
            conn.execute(ins_q, (document_id, idx, content, vector))
        conn.commit()
        print(f"  ↳ chunk {len(chunks)}건 저장 완료 (→ document_{slug}_chunk)")


def _search_subquery(slug: str, major_filter: bool) -> tuple[sql.Composable, list]:
    """카테고리 하나에 대한 DISTINCT ON 서브쿼리 Composable + placeholder 순서대로의 params.

    placeholder 순서: [vec, (major, major)?, vec]
    """
    category_literal = SLUG_TO_CATEGORY[slug]

    where_clause = (
        sql.SQL(" WHERE (s.department = %s OR %s = ANY(d.target) OR '전체' = ANY(d.target)) ")
        if major_filter else sql.SQL(" ")
    )

    sub = sql.SQL("""
        SELECT DISTINCT ON (d.id)
               d.url, d.title, c.content,
               1 - (c.embedding <=> %s::vector) AS score,
               d.start_date, d.end_date,
               {cat_lit}::text AS category,
               d.target, d.keywords,
               s.code, s.name, s.kind, s.department
        FROM {chunk} c
        JOIN {doc} d ON d.id = c.document_id
        JOIN source s ON s.id = d.source_id
        {where}
        ORDER BY d.id, c.embedding <=> %s::vector
    """).format(
        cat_lit=sql.Literal(category_literal),
        chunk=_chunk_ident(slug),
        doc=_doc_ident(slug),
        where=where_clause,
    )
    return sub, [category_literal]  # placeholder 자리 표시용; 실제로는 아래에서 다시 채움


def search_chunks(
    query_embedding: list[float],
    major: str | None = None,
    categories: list[str] | None = None,
    limit: int = 10,
):
    """HNSW 코사인 유사도 검색. 각 document당 가장 좋은 청크 1개만 추려서 반환.

    categories: 검색 대상 카테고리 리스트(한글). None 또는 빈 리스트면 5개 전부 검색.

    반환 튜플:
    (url, title, snippet, score, start_date, end_date, category, target, keywords,
     source_code, source_name, source_kind, source_department)
    """
    target_slugs = [_slug(c) for c in categories] if categories else list(SLUGS)

    subs: list[sql.Composable] = []
    params: list = []
    for slug in target_slugs:
        sub, _ = _search_subquery(slug, major_filter=bool(major))
        subs.append(sql.SQL("(") + sub + sql.SQL(")"))
        # subquery placeholder 순서: 1st vec, (major, major)?, 2nd vec(ORDER BY)
        params.append(query_embedding)
        if major:
            params.extend([major, major])
        params.append(query_embedding)

    union = sql.SQL(" UNION ALL ").join(subs)
    final_q = sql.SQL("""
        SELECT url, title, content, score, start_date, end_date,
               category, target, keywords,
               code, name, kind, department
        FROM ({union}) merged
        ORDER BY score DESC
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with _connect_with_vector() as conn:
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()


def _list_subquery(slug: str, where: sql.Composable) -> sql.Composable:
    """get_documents용 카테고리 단위 서브쿼리."""
    return sql.SQL("""
        SELECT d.url, d.title, d.content, d.start_date, d.end_date,
               {cat_lit}::text AS category,
               d.target, d.keywords,
               s.code, s.name, s.kind, s.department
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
    """document_{slug} + source join. category None이면 5개 UNION ALL.

    반환 튜플:
    (url, title, content, start_date, end_date, category, target, keywords,
     source_code, source_name, source_kind, source_department)
    """
    target_slugs = [_slug(category)] if category else list(SLUGS)

    conditions: list[sql.Composable] = []
    base_params: list = []
    if major:
        conditions.append(sql.SQL("(s.department = %s OR %s = ANY(d.target) OR '전체' = ANY(d.target))"))
        base_params.extend([major, major])
    if kind:
        conditions.append(sql.SQL("s.kind = %s"))
        base_params.append(kind)
    if department:
        conditions.append(sql.SQL("s.department = %s"))
        base_params.append(department)
    where = (
        sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        if conditions else sql.SQL("")
    )

    subs = [sql.SQL("(") + _list_subquery(slug, where) + sql.SQL(")") for slug in target_slugs]
    params: list = []
    for _ in target_slugs:
        params.extend(base_params)

    union = sql.SQL(" UNION ALL ").join(subs)
    final_q = sql.SQL("""
        SELECT *
        FROM ({union}) merged
        ORDER BY end_date ASC NULLS LAST
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with psycopg.connect(DB_URL) as conn:
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()
