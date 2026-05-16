import sitecustomize  # noqa: F401  # project-level pycache routing

from datetime import date, datetime

from crawlers import CRAWLERS
from refine import refine
from db import init_db, upsert_source, insert_document, insert_assets, insert_chunks, document_exists
from embed import embed_chunks


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
    init_db()

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

            # 이중 안전망 — 크롤러가 should_skip을 무시해도 여기서 한 번 더 거름.
            if document_exists(item["url"]):
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
            print(f'assets: {len(assets)}건')

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
                posted_at=posted_at,
            )
            insert_assets(doc.category, document_id, assets)

            chunks = embed_chunks(f"{doc.title}\n\n{doc.content}")
            insert_chunks(doc.category, document_id, chunks)
            inserted_count += 1

        print(
            f"2. 크롤링/적재 완료: 수집 {crawled_count}개, "
            f"신규 저장 {inserted_count}개, 중복 스킵 {skipped_count}개, refine 드롭 {dropped_count}개"
        )
