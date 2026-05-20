import logging
import psycopg
from psycopg import sql
from pgvector.psycopg import register_vector

from config import DB_URL, EMBEDDING_DIM, HNSW_EF_SEARCH

logger = logging.getLogger(__name__)


# schema.py의 category Literal과 1:1 매핑 — SQL 식별자에 한글/슬래시 못 쓰므로 영문 슬러그로 변환.
CATEGORY_SLUGS: dict[str, str] = {
    "장학/등록": "scholarship",
    "학사/수업": "academic",
    "진로/취업": "career",
    "행사/공모전": "event",
    "일반/기타": "etc",
    "규정/학칙": "regulation",
}
SLUG_TO_CATEGORY: dict[str, str] = {v: k for k, v in CATEGORY_SLUGS.items()}
SLUGS: list[str] = list(CATEGORY_SLUGS.values())

# UI 노출에서 제외할 카테고리. RAG retriever(search_chunks) 는 SLUGS 전체를 그대로 검색하므로
# 챗봇 답변 컨텍스트에는 들어가지만, get_documents 가 채우는 notices/home 카드 목록에는 안 보임.
_HIDDEN_SLUGS = {"regulation"}
_VISIBLE_SLUGS: list[str] = [s for s in SLUGS if s not in _HIDDEN_SLUGS]


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


def reset_db():
    """category별 document/chunk 물리 분리 스키마 생성. 기존 단일 document 잔재는 DROP."""
    with psycopg.connect(DB_URL) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # 이전 스키마(단일 document, document_asset) 잔재 제거
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
                department VARCHAR(100)
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
                    posted_at DATE,
                    start_date DATE,
                    end_date DATE,
                    target VARCHAR(100)[],
                    keywords VARCHAR(50)[],
                    crawled_at TIMESTAMPTZ DEFAULT now()
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
            conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {doc}(posted_at);").format(
                idx=sql.Identifier(f"idx_document_{slug}_posted_at"),
                doc=_doc_ident(slug),
            ))

            conn.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {chunk} (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES {doc}(id) ON DELETE CASCADE,
                    chunk_idx INT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({dim}) NOT NULL,
                    UNIQUE(document_id, chunk_idx)
                );
            """).format(
                chunk=_chunk_ident(slug),
                doc=_doc_ident(slug),
                dim=sql.SQL(str(EMBEDDING_DIM)),
            ))
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                student_id VARCHAR(20) PRIMARY KEY,
                major VARCHAR(50),
                name VARCHAR(50),
                year INT,
                interests TEXT
            );
        """)
        conn.commit()
        logger.info("✅ source + %d개 category 테이블(%s) + users 생성 완료",
                    len(SLUGS), ", ".join(SLUGS))


def upsert_source(code: str, name: str, kind: str, department: str | None) -> int:
    """source 테이블에 UPSERT 후 id 반환."""
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute("""
            INSERT INTO source (code, name, kind, department)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                kind = EXCLUDED.kind,
                department = EXCLUDED.department
            RETURNING id;
        """, (code, name, kind, department))
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


def delete_document_by_url(url: str) -> int:
    """URL로 5개 category 테이블을 훑어 일치하는 문서·청크를 삭제.

    chunks는 FK ON DELETE CASCADE로 자동 정리. 재크롤 테스트 전 기존 레코드를 깔끔히 비울 용도.
    """
    total = 0
    with psycopg.connect(DB_URL) as conn:
        for slug in SLUGS:
            del_q = sql.SQL("DELETE FROM {} WHERE url = %s;").format(_doc_ident(slug))
            cur = conn.execute(del_q, (url,))
            total += cur.rowcount or 0
        conn.commit()
    if total:
        logger.info("🗑  url 삭제 완료 — %d개 document + 종속 chunk 제거", total)
    return total


_DATE_SENTINELS = {"", "null", "none", "n/a", "na", "미정", "미상", "없음", "-"}


def _normalize_date(value):
    """LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.

    date/datetime 객체는 그대로 통과. Postgres date 컬럼이 sentinel을 거부하는 문제 차단.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if value.strip().lower() in _DATE_SENTINELS:
        return None
    return value


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
    posted_at=None,
) -> int:
    """category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환."""
    slug = _slug(category)

    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)
    posted_at = _normalize_date(posted_at)

    query = sql.SQL("""
        INSERT INTO {doc}
            (source_id, url, title, content, posted_at, start_date, end_date,
             target, keywords)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET
            source_id = EXCLUDED.source_id,
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            posted_at = EXCLUDED.posted_at,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            target = EXCLUDED.target,
            keywords = EXCLUDED.keywords
        RETURNING id;
    """).format(doc=_doc_ident(slug))

    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(query, (source_id, url, title, content, posted_at,
                                   start_date, end_date,
                                   target, keywords))
        row = cur.fetchone()
        assert row is not None
        document_id = row[0]
        conn.commit()
        logger.info("✅ [%s] document_%s 저장 완료 (id=%d)", title, slug, document_id)
        return document_id


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

    # chunks 튜플의 순서는 SQL의 (document_id, chunk_idx, content, embedding)와 맞춰 재구성.
    rows = [(document_id, idx, content, vector) for idx, content, vector in chunks]
    with _connect_with_vector() as conn:
        conn.execute(del_q, (document_id,))
        with conn.cursor() as cur:
            cur.executemany(ins_q, rows)
        conn.commit()
        logger.info("  ↳ chunk %d건 저장 완료 (→ document_%s_chunk)", len(chunks), slug)


def _search_subquery(slug: str, major_filter: bool, kind_filter: bool) -> tuple[sql.Composable, list]:
    """카테고리 하나에 대한 청크 단위 서브쿼리 Composable.

    placeholder 순서: [vec, (major, major)?, (kind)?]
    바깥 쿼리에서 score DESC 로 정렬·LIMIT 하므로 여기서는 ORDER BY 하지 않는다.
    """
    category_literal = SLUG_TO_CATEGORY[slug]

    conds: list[sql.Composable] = []
    if major_filter:
        conds.append(sql.SQL("(s.department = %s OR %s = ANY(d.target) OR '전체' = ANY(d.target))"))
    if kind_filter:
        conds.append(sql.SQL("s.kind = %s"))
    where_clause = (
        sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conds)
        if conds else sql.SQL(" ")
    )

    sub = sql.SQL("""
        SELECT d.url, d.title, c.content,
               1 - (c.embedding <=> %s::vector) AS score,
               d.posted_at, d.start_date, d.end_date,
               {cat_lit}::text AS category,
               d.target, d.keywords,
               s.code, s.name, s.kind, s.department
        FROM {chunk} c
        JOIN {doc} d ON d.id = c.document_id
        JOIN source s ON s.id = d.source_id
        {where}
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
    kind: str | None = None,
    limit: int = 10,
):
    """HNSW 코사인 유사도 검색. 청크 단위로 score 상위 N개 반환 (문서 중복 허용).

    categories: 검색 대상 카테고리 리스트(한글). None 또는 빈 리스트면 5개 전부 검색.
    kind: source.kind 필터('notice' 또는 'academic'). None이면 전체.

    반환 튜플:
    (url, title, snippet, score, posted_at, start_date, end_date, category, target, keywords,
     source_code, source_name, source_kind, source_department)
    """
    target_slugs = [_slug(c) for c in categories] if categories else list(SLUGS)

    subs: list[sql.Composable] = []
    params: list = []
    for slug in target_slugs:
        sub, _ = _search_subquery(slug, major_filter=bool(major), kind_filter=bool(kind))
        subs.append(sql.SQL("(") + sub + sql.SQL(")"))
        # subquery placeholder 순서: vec, (major, major)?, (kind)?
        params.append(query_embedding)
        if major:
            params.extend([major, major])
        if kind:
            params.append(kind)

    union = sql.SQL(" UNION ALL ").join(subs)
    final_q = sql.SQL("""
        SELECT url, title, content, score, posted_at, start_date, end_date,
               category, target, keywords,
               code, name, kind, department
        FROM ({union}) merged
        ORDER BY score DESC
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with _connect_with_vector() as conn:
        # HNSW 후보 큐 크기 — 트랜잭션 한정으로 적용. 기본 40 → recall 보강.
        # SET은 파라미터 placeholder 미지원이라 int 검증 후 인라인.
        conn.execute(sql.SQL("SET LOCAL hnsw.ef_search = {n};").format(
            n=sql.SQL(str(int(HNSW_EF_SEARCH)))
        ))
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()


def get_document_content(category: str, url: str) -> str | None:
    """url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용."""
    slug = _slug(category)
    q = sql.SQL("SELECT content FROM {doc} WHERE url = %s").format(doc=_doc_ident(slug))
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(q, (url,))
        row = cur.fetchone()
        return row[0] if row else None


def _list_subquery(slug: str, where: sql.Composable) -> sql.Composable:
    """get_documents용 카테고리 단위 서브쿼리."""
    return sql.SQL("""
        SELECT d.url, d.title, d.content, d.posted_at, d.start_date, d.end_date,
               {cat_lit}::text AS category,
               d.target, d.keywords,
               s.code, s.name, s.kind, s.department,
               d.crawled_at
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
    (url, title, content, posted_at, start_date, end_date, category, target, keywords,
     source_code, source_name, source_kind, source_department)

    정렬: posted_at(원본 등록일) 내림차순. NULL은 crawled_at(크롤링 시각)으로 fallback.
    """
    target_slugs = [_slug(category)] if category else list(_VISIBLE_SLUGS)

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
    # crawled_at은 정렬 보조용으로만 쓰고 최종 SELECT에서는 제외 (반환 튜플 안정성 유지).
    final_q = sql.SQL("""
        SELECT url, title, content, posted_at, start_date, end_date,
               category, target, keywords,
               code, name, kind, department
        FROM ({union}) merged
        ORDER BY COALESCE(posted_at::timestamp, crawled_at) DESC NULLS LAST
        LIMIT %s
    """).format(union=union)
    params.append(limit)

    with psycopg.connect(DB_URL) as conn:
        cursor = conn.execute(final_q, params)
        return cursor.fetchall()


# ── user profile ────────────────────────────────────────────────

def ensure_users_schema():
    """init_db를 거치지 않고 app만 띄운 환경도 흡수. 멱등하므로 매 호출 안전."""
    with psycopg.connect(DB_URL) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                student_id VARCHAR(20) PRIMARY KEY,
                major VARCHAR(50),
                name VARCHAR(50),
                year INT,
                interests TEXT
            );
        """)
        conn.commit()


def get_user(student_id: str) -> dict | None:
    """users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다."""
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            "SELECT student_id, name, major, year, interests FROM users WHERE student_id = %s;",
            (student_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    sid, name, major, year, interests = row
    return {
        "student_id": sid,
        "name": name,
        "major": major,
        "year": year,
        "interests": [s.strip() for s in (interests or "").split(",") if s.strip()],
    }


def upsert_user(student_id: str, name: str, major: str, year: int | None, interests: list[str]):
    """profile UPSERT. interests는 콤마 문자열로 저장."""
    interests_csv = ",".join(interests or [])
    with psycopg.connect(DB_URL) as conn:
        conn.execute("""
            INSERT INTO users (student_id, name, major, year, interests)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (student_id) DO UPDATE SET
                name = EXCLUDED.name,
                major = EXCLUDED.major,
                year = EXCLUDED.year,
                interests = EXCLUDED.interests;
        """, (student_id, name, major, year, interests_csv))
        conn.commit()
