import sitecustomize  # noqa: F401  # project-level pycache routing

from datetime import date, datetime

from crawlers import CRAWLERS
from pipelines.refine import refine
from db import (
    init_db,
    archive_documents,
    sync_pinned_urls,
    upsert_source,
    insert_document,
    insert_assets,
    insert_chunks,
    document_exists,
    delete_documents_by_source,
)
from embedding.embed import embed_document_chunks


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


def run_ingest() -> dict:
    """전체 크롤러 증분 수집 1회. 합산 카운트를 반환한다(워커 로그·모니터링용).

    DB에 이미 있는 글은 should_skip으로 건너뛰므로 반복 실행해도 안전하다.
    """
    init_db()
    total = {"crawled": 0, "inserted": 0, "skipped": 0, "dropped": 0}
    pinned_urls: set[str] = set()
    for crawler in CRAWLERS:
        collect_pinned_urls = getattr(crawler, "collect_pinned_urls", None)
        if collect_pinned_urls:
            try:
                pinned_urls.update(collect_pinned_urls())
            except Exception as e:
                print(f"  ⚠️ 고정 공지 수집 실패 [{crawler.SOURCE_CODE}] — {type(e).__name__}: {e}")
    sync_pinned_urls(pinned_urls)
    archive_documents(retention_months=24, protected_urls=pinned_urls)

    for mod in CRAWLERS:
        source_id = upsert_source(
            code=mod.SOURCE_CODE,
            name=mod.SOURCE_NAME,
            kind=mod.KIND,
            department=mod.DEPARTMENT,
            base_url=mod.BASE_URL,
        )
        print(f"[{mod.SOURCE_CODE}] source 등록 완료 (id={source_id})")

        print(f"1. 크롤링 시작: {mod.SOURCE_NAME}")
        # should_skip을 넘기면 크롤러가 DB에 이미 있는 글의 상세 진입·OCR 자체를 건너뜀.
        crawled_count = 0
        inserted_count = 0
        skipped_count = 0
        dropped_count = 0

        for item in mod.crawling(should_skip=document_exists):
            crawled_count += 1

            replace_by_source = bool(item.get("replace_by_source"))

            if replace_by_source:
                deleted = delete_documents_by_source(source_id)
                print(
                    f"   ↳ replace mode: 기존 문서 {deleted}건 삭제 후 최신 문서로 교체"
                )

            # 이중 안전망 — 크롤러가 should_skip을 무시해도 여기서 한 번 더 거름.
            if (not replace_by_source) and document_exists(item["url"]):
                skipped_count += 1
                print(f"   ↳ 이미 적재됨: {item['url']}")
                continue

            posted_at = _parse_posted_date(item.get("date"))
            refined_data = refine([item])
            if not refined_data:
                dropped_count += 1
                print(f"   ↳ refine 실패로 스킵: {item['url']}")
                continue

            doc, assets, extra = refined_data[0]
            print(f'제목: {doc.title}')
            print(f'카테고리: {doc.category}')
            print(f'대상: {doc.target}')
            print(f'등록일: {posted_at}')
            print(f'접수 시작일: {doc.start_date}')
            print(f'접수 마감일: {doc.end_date}')
            print(f'url: {doc.url}')
            print(f'keywords: {doc.keywords}')
            print(f'요약: {doc.summary}')
            print(f'assets: {len(assets)}건')

            document_id = insert_document(
                source_id=source_id,
                url=doc.url,
                title=doc.title,
                content=doc.content,

                # 신규 구조
                body_content=item.get("body_content"),

                category=doc.category,
                summary=doc.summary,
                topics=doc.topics,
                series_key=doc.series_key,
                periods=doc.periods,
                audiences=doc.audiences,
                application=doc.application,
                extraction_confidence=doc.extraction_confidence,
                extra=extra,
                posted_at=posted_at,
                is_pinned=bool(item.get("is_pinned")),
            )
            insert_assets(document_id, assets)

            base_body_content = (
                item.get("body_content")
                or doc.content
                or ""
            )

            inline_image_texts: list[str] = []
            for asset in assets:
                if asset.get("kind") != "inline_image":
                    continue

                ocr_text = (
                    asset.get("ocr_text")
                    or asset.get("text")
                    or ""
                ).strip()

                if not ocr_text:
                    continue

                inline_image_texts.append(
                    f"[본문 이미지 OCR]\n{ocr_text}"
                )

            merged_body_content = base_body_content
            if inline_image_texts:
                merged_body_content += "\n\n" + "\n\n".join(inline_image_texts)

            chunks = embed_document_chunks(
                title=doc.title,
                body_content=merged_body_content,
                attachment_contents=(
                    item.get("attachment_contents")
                    or []
                ),
            )

            insert_chunks(document_id, chunks)
            inserted_count += 1

        print(
            f"2. 크롤링/적재 완료: 수집 {crawled_count}개, "
            f"신규 저장 {inserted_count}개, 중복 스킵 {skipped_count}개, refine 드롭 {dropped_count}개"
        )
        total["crawled"] += crawled_count
        total["inserted"] += inserted_count
        total["skipped"] += skipped_count
        total["dropped"] += dropped_count

    return total


if __name__ == "__main__":
    run_ingest()
