"""
공지사항 URL 하나를 크롤링하여 텍스트 보고서를 작성합니다.

이 작업은 데이터베이스를 초기화하거나 기록하지 않습니다.
대신, 실제 앱 파이프라인에서 사용하는 동일한 주요 단계들을 그대로 실행합니다.

포함되는 단계:
    - 크롤러 상세페이지 수집
    - 첨부파일 다운로드 및 텍스트 추출
    - OCR / synap preview 기반 추출
    - LLM 메타데이터 정제(refine)
    - body / attachment 기반 chunk 생성
    - 임베딩 생성

또한 운영 ingest.py 와 동일하게:
    - attachment/body chunk 분리
    - replace_by_source 처리
    - DB 저장 (--db-write)

동작을 테스트할 수 있습니다.


실행방법(터미널):
    python3 debugtools/crawl_one.py "공지사항(url)"

추가 설정:
    --crawler
        크롤러 선택 가능
        (default: main_notice)

    --output
        보고서 txt 저장 경로 지정 가능
        (default: crawl_result/reports/crawl_one_<time>_<hash>.txt)

    --db-write
        refine/chunk/embed 결과를 실제 DB에 저장

        예시:
            python3 debugtools/crawl_one.py "URL" --db-write
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sitecustomize  # noqa: F401  # project-level pycache routing
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from crawlers import CRAWLERS
import crawlers.methods.board_notice as board_notice
from db import (
    delete_documents_by_source,
    document_exists,
    init_db,
    insert_assets,
    insert_chunks,
    insert_document,
    upsert_source,
)
from embedding.embed import embed_chunks
from ingest import _parse_posted_date
from refine import refine


REPORT_DIR = PROJECT_ROOT / "crawl_result/reports"


def _crawler_map():
    return {crawler.SOURCE_CODE: crawler for crawler in CRAWLERS}


def _require_board_crawler(crawler) -> None:
    if not hasattr(crawler, "_crawl_detail"):
        raise TypeError(
            f"{crawler.SOURCE_CODE} is not a board-detail crawler; "
            "choose a crawler with _crawl_detail()."
        )


def _default_report_path(url: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return REPORT_DIR / f"crawl_one_{stamp}_{digest}.txt"


def _preview(text: str, limit: int = 300) -> str:
    clean = text.replace("\r", "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "\n... [truncated preview]"


def _write_section(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append("=" * 80)
    lines.append(title)
    lines.append("=" * 80)


def crawl_detail(crawler, url: str) -> dict:
    _require_board_crawler(crawler)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            return crawler._crawl_detail(context, page, url, 1, 1)
        finally:
            browser.close()


def build_report(
    *,
    crawler,
    url: str,
    item: dict,
    refined,
    refine_error: Exception | None,
    chunks,
    embedding_error: Exception | None,
) -> str:
    assets = item.get("assets", [])
    posted_at = _parse_posted_date(item.get("date"))
    lines: list[str] = []

    _write_section(lines, "Run")
    lines.append(f"created_at: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"crawler: {crawler.SOURCE_CODE} / {crawler.SOURCE_NAME}")
    lines.append(f"url: {url}")
    lines.append("db_write: report-only mode")
    lines.append(f"replace_by_source: {bool(item.get('replace_by_source'))}")
    lines.append("xlsx_filter: forced include for single-url attachment testing")

    _write_section(lines, "Crawl Result")
    lines.append(f"title: {item.get('title')}")
    lines.append(f"raw_date: {item.get('date')}")
    lines.append(f"posted_at: {posted_at}")
    lines.append(f"content_chars: {len(item.get('content') or '')}")
    lines.append(f"assets_count: {len(assets)}")
    lines.append(f"assets_by_kind: {dict(Counter(a.get('kind') for a in assets))}")

    _write_section(lines, "Assets")
    if not assets:
        lines.append("(none)")
    for idx, asset in enumerate(assets, 1):
        extracted = asset.get("extracted_text") or ""
        lines.append(f"[{idx}] kind: {asset.get('kind')}")
        lines.append(f"filename: {asset.get('filename')}")
        lines.append(f"source_url: {asset.get('source_url')}")
        lines.append(f"mime_type: {asset.get('mime_type')}")
        lines.append(f"storage_path: {asset.get('storage_path')}")
        lines.append(f"extracted_chars: {len(extracted)}")
        lines.append("extracted_preview:")
        lines.append(_preview(extracted))
        lines.append("-" * 80)

    _write_section(lines, "LLM Refine")
    if refine_error:
        lines.append(f"status: failed ({type(refine_error).__name__})")
        lines.append(str(refine_error))
    elif not refined:
        lines.append("status: failed (empty refine result)")
    else:
        doc, _, extra = refined[0]
        lines.append("status: ok")
        lines.append(f"category: {doc.category}")
        lines.append(f"summary: {doc.summary}")
        lines.append(f"target: {doc.target}")
        lines.append(f"start_date: {doc.start_date}")
        lines.append(f"end_date: {doc.end_date}")
        lines.append(f"keywords: {doc.keywords}")
        lines.append(f"extra: {extra}")

    _write_section(lines, "Embedding Chunks")
    if embedding_error:
        lines.append(f"status: failed ({type(embedding_error).__name__})")
        lines.append(str(embedding_error))
    else:
        lines.append("status: ok")
        lines.append(f"chunks_count: {len(chunks)}")
        if chunks:
            lines.append(f"embedding_dim: {len(chunks[0][2])}")
        for chunk in chunks:
            if len(chunk) == 3:
                idx, chunk_text, vector = chunk
                chunk_type = "legacy"
                attachment_name = None
            else:
                idx, chunk_text, vector, chunk_type, attachment_name = chunk

            lines.append("")
            lines.append(
                f"--- chunk {idx} | "
                f"type={chunk_type} | "
                f"attachment={attachment_name} | "
                f"chars={len(chunk_text)} | "
                f"dim={len(vector)} ---"
            )

            lines.append(chunk_text)

    _write_section(lines, "Full Crawled Content")
    lines.append(item.get("content") or "")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Crawl one notice URL and write a txt report.")
    parser.add_argument("url", help="Notice detail URL to crawl")
    parser.add_argument(
        "--crawler",
        default="main_notice",
        help="Crawler SOURCE_CODE to use. Default: main_notice",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Report txt path. Default: crawl_result/reports/crawl_one_<time>_<hash>.txt",
    )
    parser.add_argument(
        "--db-write",
        action="store_true",
        help="Also write crawled/refined/chunked result into DB",
    )
    args = parser.parse_args()

    crawlers = _crawler_map()
    if args.crawler not in crawlers:
        available = ", ".join(sorted(crawlers))
        raise SystemExit(f"Unknown crawler: {args.crawler}. Available: {available}")

    # Single-url testing should exercise XLSX extraction regardless of the
    # production relevance keyword filter.
    board_notice.xlsx_relevant = lambda *texts: True

    crawler = crawlers[args.crawler]
    report_path = args.output or _default_report_path(args.url)

    print(f"crawler: {crawler.SOURCE_CODE} / {crawler.SOURCE_NAME}")
    print(f"url: {args.url}")
    print(f"db_write: {'enabled' if args.db_write else 'skipped'}")

    item = crawl_detail(crawler, args.url)

    refined = []
    refine_error: Exception | None = None
    try:
        refined = refine([item])
    except Exception as exc:
        refine_error = exc
        print("\n[refine traceback]")
        traceback.print_exc()

    chunks = []
    embedding_error: Exception | None = None
    try:
        title = item.get("title") or ""

        body_content = item.get("body_content") or item.get("content") or ""

        attachment_contents = item.get("attachment_contents") or []

        chunk_inputs: list[tuple[str, str, str | None]] = []

        # body chunk
        if body_content.strip():
            chunk_inputs.append(
                (
                    "body",
                    body_content,
                    None,
                )
            )

        # attachment chunks
        for att in attachment_contents:
            text = (att.get("text") or "").strip()

            if not text:
                continue

            chunk_inputs.append(
                (
                    "attachment",
                    text,
                    att.get("name"),
                )
            )

        chunks = []

        chunk_idx = 0

        for chunk_type, text, attachment_name in chunk_inputs:
            embedded = embed_chunks(f"{title}\n\n{text}")

            for _, chunk_text, vector in embedded:
                chunks.append(
                    (
                        chunk_idx,
                        chunk_text,
                        vector,
                        chunk_type,
                        attachment_name,
                    )
                )

                chunk_idx += 1

    except Exception as exc:
        embedding_error = exc
        print("\n[embedding traceback]")
        traceback.print_exc()

    report = build_report(
        crawler=crawler,
        url=args.url,
        item=item,
        refined=refined,
        refine_error=refine_error,
        chunks=chunks,
        embedding_error=embedding_error,
    )

    if args.db_write:
        if refine_error:
            print(f"[db] skipped: refine failed ({type(refine_error).__name__})")
        elif not refined:
            print("[db] skipped: empty refine result")
        elif embedding_error:
            print(f"[db] skipped: embedding failed ({type(embedding_error).__name__})")
        else:
            try:
                init_db()

                doc, assets, extra = refined[0]

                source_id = upsert_source(
                    code=crawler.SOURCE_CODE,
                    name=crawler.SOURCE_NAME,
                    kind=crawler.KIND,
                    department=crawler.DEPARTMENT,
                    base_url=crawler.BASE_URL,
                )

                replace_by_source = bool(item.get("replace_by_source"))

                if replace_by_source:
                    print(f"[db] replace_by_source enabled: source_id={source_id}")
                    delete_documents_by_source(source_id)

                if not replace_by_source and document_exists(doc.url):
                    print(f"[db] already exists: {doc.url}")
                else:
                    posted_at = _parse_posted_date(item.get("date"))

                    document_id = insert_document(
                        source_id=source_id,
                        url=doc.url,
                        title=doc.title,
                        content=doc.content,

                        # 신규 구조
                        body_content=item.get("body_content"),
                        attachment_names=item.get("attachment_names"),
                        attachment_contents=item.get("attachment_contents"),

                        start_date=doc.start_date,
                        end_date=doc.end_date,
                        category=doc.category,
                        target=doc.target,
                        keywords=doc.keywords,
                        summary=doc.summary,
                        extra=extra,
                        posted_at=posted_at,
                        is_pinned=bool(item.get("is_pinned")),
                    )

                    insert_assets(doc.category, document_id, assets)
                    insert_chunks(doc.category, document_id, chunks)

                    print(f"[db] saved: document_id={document_id}")

            except Exception as e:
                print(f"[db] failed: {type(e).__name__}: {e}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"report: {report_path}")
    print(f"content_chars: {len(item.get('content') or '')}")
    print(f"assets: {len(item.get('assets') or [])}")
    print(f"refine: {'failed' if refine_error or not refined else 'ok'}")
    print(f"chunks: {'failed' if embedding_error else len(chunks)}")


if __name__ == "__main__":
    main()
