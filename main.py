import logging
import os
from datetime import date, datetime

from crawlers import CRAWLERS
from refine import refine
from db import reset_db, upsert_source, insert_document, insert_assets, insert_chunks, document_exists
from embed import embed_chunks

logger = logging.getLogger(__name__)


def _parse_posted_date(raw: str | None) -> date | None:
    """크롤러가 수집한 원본 등록일 문자열을 date로 변환. 실패하면 None.

    공주대 사이트들이 흔히 쓰는 'YYYY.MM.DD', 'YYYY-MM-DD', 'YYYY/MM/DD'(+ 선택적 시각) 형태를 흡수한다.
    """
    if not raw:
        return None
    s = raw.strip()
    if not s or "찾을 수 없음" in s:
        return None
    # 시각이 붙어 있으면 날짜 부분만 사용
    s = s.split()[0]
    s = s.replace(".", "-").replace("/", "-").rstrip("-")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        y, m, d = (int(p) for p in s.split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    # ONLY_SOURCE=<code> 로 단일 소스만 재크롤링. 이 모드에선 init_db()를 건너뛰어
    # 다른 소스의 기존 데이터가 보존된다. (reset_db는 모든 document/chunk를 DROP한다.)
    only = os.getenv("ONLY_SOURCE")
    if only:
        crawlers = [m for m in CRAWLERS if m.SOURCE_CODE == only]
        if not crawlers:
            raise SystemExit(f"ONLY_SOURCE={only!r} 에 해당하는 크롤러 없음")
        logger.info("단일 소스 모드: %s (init_db 스킵)", only)
    else:
        crawlers = list(CRAWLERS)
        # 스키마 실패는 즉시 fail-fast — try 밖에서 호출.
        reset_db()

    failed_sources: list[tuple[str, str]] = []
    failed_docs: list[tuple[str, str]] = []

    for mod in crawlers:
        try:
            source_id = upsert_source(
                code=mod.SOURCE_CODE,
                name=mod.SOURCE_NAME,
                kind=mod.KIND,
                department=mod.DEPARTMENT,
                base_url=mod.BASE_URL,
            )
            logger.info("[%s] source 등록 완료 (id=%d)", mod.SOURCE_CODE, source_id)

            logger.info("1. 크롤링 시작: %s", mod.SOURCE_NAME)
            # should_skip을 넘기면 크롤러가 페이지 단위에서 DB에 이미 있는 글의 상세 진입·OCR 자체를 건너뜀.
            # BoardNoticeCrawler가 generator라 list()로 흡수 — batch refine 흐름 유지 위해.
            crawled = list(mod.crawling(should_skip=document_exists))
            logger.info("2. 크롤링 완료: %d개", len(crawled))

            # 이중 안전망 — 크롤러가 should_skip을 무시해도 여기서 한 번 더 거름.
            fresh = [item for item in crawled if not document_exists(item["url"])]
            skipped = len(crawled) - len(fresh)
            if skipped:
                logger.info("   ↳ 이미 적재된 %d개 건너뜀, 신규 %d개만 처리", skipped, len(fresh))
            if not fresh:
                continue

            refined_data = refine(fresh)

            # refine은 일부 항목을 드롭할 수 있으므로 url로 원본 등록일을 다시 매핑.
            posted_by_url = {item["url"]: _parse_posted_date(item.get("date")) for item in fresh}
        except Exception as e:
            logger.warning("source 실패 [%s]: %s", mod.SOURCE_CODE, e, exc_info=True)
            failed_sources.append((mod.SOURCE_CODE, str(e)))
            continue

        for doc, assets, extra in refined_data:
            try:
                logger.info(
                    "제목: %s | 카테고리: %s | 대상: %s | 등록일: %s | 접수: %s ~ %s | url: %s | keywords: %s | assets: %d건",
                    doc.title, doc.category, doc.target, posted_by_url.get(doc.url),
                    doc.start_date, doc.end_date, doc.url, doc.keywords, len(assets),
                )

                document_id = insert_document(
                    source_id=source_id,
                    url=doc.url,
                    title=doc.title,
                    content=doc.content,
                    start_date=doc.start_date,
                    end_date=doc.end_date,
                    category=doc.category,
                    target=doc.target,
                    keywords=doc.keywords,
                    extra=extra,
                    posted_at=posted_by_url.get(doc.url),
                )
                insert_assets(doc.category, document_id, assets)

                chunks = embed_chunks(f"{doc.title}\n\n{doc.content}")
                insert_chunks(doc.category, document_id, chunks)
            except Exception as e:
                logger.warning("doc 실패 [%s]: %s", doc.url, e, exc_info=True)
                failed_docs.append((doc.url, str(e)))

    # ── 종료 요약 ────────────────────────────────────────────────
    logger.info("=== 크롤링 종료 ===")
    logger.info("실패 source: %d개 / 실패 doc: %d개", len(failed_sources), len(failed_docs))
    for code, err in failed_sources:
        logger.info("  [source] %s: %s", code, err)
    for url, err in failed_docs:
        logger.info("  [doc] %s: %s", url, err)
