"""DB document_*만으로 청크/임베딩 재생성. 크롤링 우회.

용도: CHUNK_SIZE / CHUNK_OVERLAP / 임베딩 정책 변경 후 전수 재처리.
비범위: provider 전환·EMBEDDING_DIM 변경은 전체 재크롤 필요.

CLI:
- 전체:     python scripts/rechunk.py
- 카테고리: python scripts/rechunk.py --category 학사/수업
- 단건:     python scripts/rechunk.py --category 학사/수업 --doc-id 1234
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 스크립트를 컨테이너 밖에서 실행해도 패키지 import 동작하도록 경로 보정.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import psycopg
from psycopg import sql

from config import DB_URL
from db import CATEGORY_SLUGS, SLUG_TO_CATEGORY, SLUGS, _doc_ident, insert_chunks
from embed import embed_chunks


_MAX_WORKERS = 5
_RETRY_ATTEMPTS = 4  # 1·2·4s exponential backoff (마지막은 raise)


def _resolve_slug(value: str) -> str:
    """한글 카테고리 또는 영문 slug 입력 정규화."""
    if value in CATEGORY_SLUGS:
        return CATEGORY_SLUGS[value]
    if value in SLUGS:
        return value
    raise SystemExit(f"unknown category/slug: {value!r}")


def _iter_documents(slug: str, doc_id: int | None):
    """document_{slug} 전수 또는 단건 SELECT 제너레이터."""
    table = _doc_ident(slug)
    if doc_id is not None:
        q = sql.SQL("SELECT id, title, content FROM {} WHERE id = %s").format(table)
        params: tuple = (doc_id,)
    else:
        q = sql.SQL("SELECT id, title, content FROM {} ORDER BY id").format(table)
        params = ()
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            yield from cur


def _embed_with_retry(text: str):
    """exponential backoff 4회. 모든 예외 retry — auth 같은 영구 에러도 최대 7s 낭비 허용."""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return embed_chunks(text)
        except Exception as e:
            if attempt == _RETRY_ATTEMPTS - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4
            print(
                f"  retry {attempt + 1}/{_RETRY_ATTEMPTS} after {wait}s: {e}",
                file=sys.stderr,
            )
            time.sleep(wait)


def _process_one(slug: str, category: str, row: tuple) -> tuple[str, int, str]:
    """document 1개 처리. 반환: (status, document_id, detail).
    status: "ok" | "skip".  실패는 예외 그대로 raise → 호출부에서 fail 카운트.
    """
    document_id, title, content = row
    if not (content or "").strip():
        return ("skip", document_id, "빈 content")
    chunks = _embed_with_retry(f"{title}\n\n{content}")
    if not chunks:
        return ("skip", document_id, "chunks 0개")
    insert_chunks(category, document_id, chunks)
    return ("ok", document_id, f"{len(chunks)} chunks")


def rechunk_category(slug: str, doc_id: int | None) -> tuple[int, int]:
    """한 카테고리 ThreadPool 재처리. (ok, fail) 반환."""
    category = SLUG_TO_CATEGORY[slug]
    rows = list(_iter_documents(slug, doc_id))
    if not rows:
        print("  (no documents)")
        return (0, 0)

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {ex.submit(_process_one, slug, category, r): r[0] for r in rows}
        for fut in as_completed(futures):
            doc_id_for_log = futures[fut]
            try:
                status, did, detail = fut.result()
                if status == "ok":
                    print(f"[ok]   {slug}#{did}: {detail}")
                    ok += 1
                else:  # skip
                    print(f"[warn] {slug}#{did}: {detail}", file=sys.stderr)
            except Exception as e:
                print(f"[fail] {slug}#{doc_id_for_log}: {e}", file=sys.stderr)
                fail += 1
    return (ok, fail)


def main() -> None:
    ap = argparse.ArgumentParser(description="DB document_*만으로 청크/임베딩 재생성.")
    ap.add_argument("--category", help="한글 카테고리 또는 영문 slug. 미지정 시 5개 전부.")
    ap.add_argument("--doc-id", type=int, help="특정 document_id만 (--category 필수).")
    args = ap.parse_args()

    if args.doc_id is not None and not args.category:
        raise SystemExit("--doc-id 사용 시 --category 필수 (id는 카테고리별 시퀀스).")

    target_slugs = [_resolve_slug(args.category)] if args.category else list(SLUGS)

    total_ok = total_fail = 0
    for slug in target_slugs:
        print(f"=== {slug} ({SLUG_TO_CATEGORY[slug]}) ===")
        ok, fail = rechunk_category(slug, args.doc_id)
        print(f"--- {slug}: ok={ok}, fail={fail}")
        total_ok += ok
        total_fail += fail
    print(f"=== done: ok={total_ok}, fail={total_fail} ===")


if __name__ == "__main__":
    main()
