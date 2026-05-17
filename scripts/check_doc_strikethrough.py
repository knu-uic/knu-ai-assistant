"""DB에 저장된 fulldoc 안에 '~~' (markdown strikethrough) 패턴이 있는지 확인.

가설:
  xlsx 첨부에서 헤더가 "2011~~2016학년도..." 형태로 저장되어 fulldoc에 '~~'가 들어가면
  LLM이 markdown strikethrough로 인식해 해당 학번 컬럼을 가치 절하할 수 있다.

실행 (docker compose):
    # 기본: 모든 slug · 모든 문서를 전수 스캔해 '~~' 포함 문서를 모두 보고
    docker compose exec app python scripts/check_doc_strikethrough.py

    # title 또는 content에 키워드 가진 문서만 검사
    docker compose exec app python scripts/check_doc_strikethrough.py --keyword "교양교과목 편성"

    # 특정 slug만
    docker compose exec app python scripts/check_doc_strikethrough.py --slug academic
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg import sql

from config import DB_URL
from db import _doc_ident, SLUGS


CONTEXT_RADIUS = 30


def _scan_doc(url: str, title: str, content: str) -> dict:
    matches = list(re.finditer(r"~~", content))
    samples = []
    for m in matches[:10]:
        start = max(0, m.start() - CONTEXT_RADIUS)
        end = min(len(content), m.end() + CONTEXT_RADIUS)
        snippet = content[start:end].replace("\n", " ")
        samples.append(snippet)
    return {
        "url": url,
        "title": title,
        "tilde_count": len(matches),
        "samples": samples,
    }


def _fetch_docs(conn, slug: str, keyword: str | None):
    if keyword:
        q = sql.SQL(
            "SELECT url, title, content FROM {doc} "
            "WHERE title LIKE %s OR content LIKE %s"
        ).format(doc=_doc_ident(slug))
        pat = f"%{keyword}%"
        return conn.execute(q, (pat, pat)).fetchall()
    q = sql.SQL("SELECT url, title, content FROM {doc}").format(doc=_doc_ident(slug))
    return conn.execute(q).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default=None,
                        help="title OR content LIKE %%keyword%% 필터. 미지정 시 전체 스캔.")
    parser.add_argument("--slug", default=None,
                        help="특정 slug만 검사. 미지정 시 모든 slug 순회.")
    args = parser.parse_args()

    target_slugs = [args.slug] if args.slug else SLUGS
    hits: list[dict] = []
    scanned = 0

    with psycopg.connect(DB_URL) as conn:
        for slug in target_slugs:
            try:
                rows = _fetch_docs(conn, slug, args.keyword)
            except Exception as e:
                print(f"[skip {slug}] {e}")
                continue
            for url, title, content in rows:
                scanned += 1
                if not content or "~~" not in content:
                    continue
                hits.append(_scan_doc(url, title, content))

    print(f"[scan] {scanned}개 문서 검사, '~~' 포함 {len(hits)}개")
    if not hits:
        kw = f" (keyword='{args.keyword}')" if args.keyword else ""
        print(f"→ '~~' 패턴 없음{kw}. 다른 원인 의심.")
        return 1

    for h in hits:
        print("=" * 60)
        print(f"[{h['title']}] {h['url']}")
        print(f"  '~~' 등장 횟수: {h['tilde_count']}")
        for i, s in enumerate(h["samples"], 1):
            print(f"  sample {i}: ...{s}...")
    total = sum(h["tilde_count"] for h in hits)
    print("=" * 60)
    print(f"총 {len(hits)}개 문서, '~~' 누적 {total}회")
    print("→ 가설 confirm: fulldoc 안에 '~~' 패턴 존재. LLM이 strikethrough로 볼 위험.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
