import psycopg
from pgvector.psycopg import register_vector
from embed import get_embeddings
from dotenv import load_dotenv
import os
load_dotenv()
DB_URL = f"postgresql://knu-uic:{os.getenv("DB_PASSWORD")}@db:5432/knu-uic"

def init_db():
    with psycopg.connect(DB_URL) as conn:
        conn.execute("DROP TABLE notice;")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.execute("""
                CREATE TABLE IF NOT EXISTS notice (
                url VARCHAR(500) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                start_date DATE,
                end_date DATE,
                category VARCHAR(50),
                target VARCHAR(100)[],
                keywords VARCHAR(50)[],
                embedding vector(3072) 
            );
        """)
        
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
        print("✅ 데이터베이스 테이블 생성 완료!")
        
def insert_notice(url, title, content, start_date, end_date, category, target, keywords):
    embedding = get_embeddings()

    if not start_date or str(start_date).strip() == "":
        start_date = None
    if not end_date or str(end_date).strip() == "":
        end_date = None

    target_str = ', '.join(target) if isinstance(target, list) else target
    keyword_str = ', '.join(keywords) if isinstance(keywords, list) else keywords

    text_to_embed = f"""
    제목: {title}
    대상: {target_str}
    내용: {content}
    키워드: {keyword_str}
    """
    vector = embedding.embed_query(text_to_embed)

    with psycopg.connect(DB_URL) as conn:
        # DB에 vector 타입을 인식시켜줍니다.
        register_vector(conn)

        # Step B: DB에 데이터 밀어넣기 (UPSERT 문법 사용)
        # URL이 이미 있으면 크롤링 중복이므로 새로운 내용으로 덮어씁니다!
        conn.execute("""
            INSERT INTO notice (url, title, content, start_date, end_date, category, target, keywords, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE SET
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                category = EXCLUDED.category,
                target = EXCLUDED.target,
                keywords = EXCLUDED.keywords,
                embedding = EXCLUDED.embedding;
        """, (url, title, content, start_date, end_date, category, target, keywords, vector)
        )
        
        conn.commit()
        print(f"✅ [{title}] DB 저장(임베딩) 완료!")
        
def search_notice(query: str, student_major: str = "전체", limit: int = 5):
    """
    query: 사용자의 검색어 (예: "해외로 갈 수 있는 프로그램 찾아줘")
    student_major: 사용자 프로필의 학과 (예: "컴퓨터공학과"). 이 학과가 타겟에 포함되거나 '전체'인 글만 찾음.
    """
    print(f"\n🔍 검색어: '{query}' / 필터링 학과: '{student_major}'")
    embeddings = get_embeddings()
    # 1. 사용자의 검색어를 벡터(숫자)로 변환
    query_vector = embeddings.embed_query(query)
    
    with psycopg.connect(DB_URL) as conn:
        register_vector(conn)
        
        # 2. 하이브리드 검색 쿼리 (pgvector의 핵심)
        # <=> 는 코사인 거리(Cosine Distance)를 의미합니다. 가까울수록(숫자가 작을수록) 유사함.
        if student_major == "전체":
            sql = """
                SELECT title, category, target, url,
                       (1 - (embedding <=> %s::vector)) AS similarity_score
                FROM notice
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            cursor = conn.execute(sql, (query_vector, query_vector, limit))
        else:
            sql = """
                SELECT title, category, target, url,
                       (1 - (embedding <=> %s::vector)) AS similarity_score
                FROM notice
                WHERE %s = ANY(target) OR '전체' = ANY(target)
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            cursor = conn.execute(sql, (query_vector, student_major, query_vector, limit))
        results = cursor.fetchall()
        
        # 3. 결과 출력
        if not results:
            print("해당 조건에 맞는 공지사항이 없습니다.")
            return []

        for row in results:
            title, category, target, url, score = row
            # score가 1에 가까울수록 검색어와 찰떡이라는 뜻입니다.
            print(f"[{score:.2f}] {title} (카테고리: {category}, 대상: {target})")
            print(f" -> 링크: {url}\n")

        return results


def get_notices(category: str | None = None, major: str | None = None, limit: int = 30):
    """
    category: 카테고리 필터 (None이면 전체)
    major: 학과 필터 (None이면 전체)
    반환: (url, title, content, start_date, end_date, category, target, keywords) 튜플 리스트
    """
    with psycopg.connect(DB_URL) as conn:
        register_vector(conn)
        conditions = []
        params = []

        if category:
            conditions.append("category = %s")
            params.append(category)

        if major:
            conditions.append("(%s = ANY(target) OR '전체' = ANY(target))")
            params.append(major)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT url, title, content, start_date, end_date, category, target, keywords
            FROM notice
            {where}
            ORDER BY end_date ASC NULLS LAST
            LIMIT %s
        """
        params.append(limit)
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

