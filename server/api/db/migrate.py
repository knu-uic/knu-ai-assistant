"""raw SQL 마이그레이션 러너.

migrations/의 번호 붙은 .sql 파일을 이름순으로, 아직 적용 안 된 것만 실행한다.
적용 기록은 schema_migrations 테이블에 남는다 (version = 파일명).

실행: python -m db.migrate
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from db.schema import DB_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def list_migrations(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def pending_migrations(applied: set[str], files: list[Path]) -> list[Path]:
    return [f for f in files if f.name not in applied]


def migrate(directory: Path = MIGRATIONS_DIR) -> list[str]:
    """미적용 마이그레이션을 순서대로 실행하고 적용한 파일명 목록을 반환한다."""
    # 배포 시점 1회성 CLI라 커넥션 풀 없이 단일 연결을 쓴다.
    with psycopg.connect(DB_URL) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(200) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        applied = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations;")
        }
        ran: list[str] = []
        for f in pending_migrations(applied, list_migrations(directory)):
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s);", (f.name,)
            )
            # 파일 단위 커밋 — 중간 실패 시 적용된 파일까지만 기록이 남는다.
            conn.commit()
            ran.append(f.name)
    return ran


if __name__ == "__main__":
    ran = migrate()
    if ran:
        print(f"✅ 적용: {', '.join(ran)}")
    else:
        print("적용할 마이그레이션 없음")
