"""
공지사항 URL 하나를 크롤링하여 텍스트 보고서를 작성합니다.
이 작업은 데이터베이스를 초기화하거나 기록하지 않습니다. 
대신, 앱 파이프라인에서 사용하는 동일한 주요 단계인 크롤러 첨부파일 추출,
LLM 메타데이터 정제, 임베딩 청크 생성 과정을 그대로 실행합니다.


실행방법(터미널):
    python3 knu-ai-assistant/crawlers/crawltest/crawl_one.py "공지사항(url)" 
추가 설정:
    --crawler 옵션으로 크롤러 선택 가능 (default: main_notice)
    --output 옵션으로 보고서 txt 경로 지정 가능 (default: crawl_result/reports/crawl_one_<time>_<hash>.txt)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sitecustomize  # noqa: F401  # project-level pycache routing
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from crawlers import CRAWLERS
import crawlers.methods.board_notice as board_notice
from embed import embed_chunks
from main import _parse_posted_date
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
    lines.append("db_write: skipped")
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
        for idx, chunk_text, vector in chunks:
            lines.append("")
            lines.append(f"--- chunk {idx} | chars={len(chunk_text)} | dim={len(vector)} ---")
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
    print("db_write: skipped")

    item = crawl_detail(crawler, args.url)

    refined = []
    refine_error: Exception | None = None
    try:
        refined = refine([item])
    except Exception as exc:
        refine_error = exc

    chunks = []
    embedding_error: Exception | None = None
    try:
        content_for_embedding = item.get("content") or ""
        title = item.get("title") or ""
        chunks = embed_chunks(f"{title}\n\n{content_for_embedding}")
    except Exception as exc:
        embedding_error = exc

    report = build_report(
        crawler=crawler,
        url=args.url,
        item=item,
        refined=refined,
        refine_error=refine_error,
        chunks=chunks,
        embedding_error=embedding_error,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"report: {report_path}")
    print(f"content_chars: {len(item.get('content') or '')}")
    print(f"assets: {len(item.get('assets') or [])}")
    print(f"refine: {'failed' if refine_error or not refined else 'ok'}")
    print(f"chunks: {'failed' if embedding_error else len(chunks)}")


if __name__ == "__main__":
    main()
