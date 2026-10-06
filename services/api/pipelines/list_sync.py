"""상세·첨부·LLM 처리 없이 공지 목록만 빠르게 동기화한다."""
from __future__ import annotations

import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from crawlers.methods.board_notice import BoardNoticeCrawler
from crawlers.registry import CRAWLERS
from db.documents import register_crawl_records, upsert_source


def _single_document_record(crawler: Any) -> dict:
    config = crawler.config
    url = config.page_url
    context = (
        ssl.create_default_context()
        if getattr(config, "verify_ssl", True)
        else ssl._create_unverified_context()
    )
    context.set_ciphers("DEFAULT@SECLEVEL=1")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, context=context, timeout=30) as response:
        status = int(getattr(response, "status", 200))
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    return {
        "url": url,
        "title": crawler.SOURCE_NAME,
        "posted_at": None,
        "is_pinned": False,
        "_crawl_page": None,
    }


def _sync_source(crawler: Any) -> dict:
    started = time.perf_counter()
    pages = 1
    if isinstance(crawler, BoardNoticeCrawler):
        pages = crawler.detect_total_pages()
        records: list[dict] = []

        def collect(page: int) -> tuple[int, list[dict]]:
            return page, crawler._collect_post_records(None, page)

        with ThreadPoolExecutor(max_workers=2) as executor:
            for page, page_records in executor.map(collect, range(1, pages + 1)):
                for record in page_records:
                    record["_crawl_page"] = page
                records.extend(page_records)
    else:
        records = [_single_document_record(crawler)]

    source_id = upsert_source(
        crawler.SOURCE_CODE,
        crawler.SOURCE_NAME,
        crawler.KIND,
        crawler.DEPARTMENT,
        crawler.BASE_URL,
    )
    counts = register_crawl_records(source_id, records)
    return {
        "code": crawler.SOURCE_CODE,
        "name": crawler.SOURCE_NAME,
        "pages": pages,
        "notices": counts["registered"],
        "new": counts["new"],
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "status": "complete",
    }


def sync_notice_lists() -> dict:
    """6개 소스를 동기화하되 한 소스의 실패가 나머지를 막지 않게 한다."""
    started = time.perf_counter()
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_sync_source, crawler): crawler for crawler in CRAWLERS}
        for future in as_completed(futures):
            crawler = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {
                    "code": crawler.SOURCE_CODE,
                    "name": crawler.SOURCE_NAME,
                    "pages": 0,
                    "notices": 0,
                    "new": 0,
                    "duration_ms": 0,
                    "status": "failed",
                    "error": str(error),
                }
            results[crawler.SOURCE_CODE] = result

    ordered = [results[crawler.SOURCE_CODE] for crawler in CRAWLERS]
    return {
        "ok": all(item["status"] == "complete" for item in ordered),
        "sources": ordered,
        "pages": sum(item["pages"] for item in ordered),
        "notices": sum(item["notices"] for item in ordered),
        "new": sum(item["new"] for item in ordered),
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }
