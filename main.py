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
        # should_skip을 넘기면 크롤러가 페이지 단위에서 DB에 이미 있는 글의 상세 진입·OCR 자체를 건너뜀.
        crawled = mod.crawling(should_skip=document_exists)
        print(f"2. 크롤링 완료: {len(crawled)}개")

        # 이중 안전망 — 크롤러가 should_skip을 무시해도 여기서 한 번 더 거름.
        fresh = [item for item in crawled if not document_exists(item["url"])]
        skipped = len(crawled) - len(fresh)
        if skipped:
            print(f"   ↳ 이미 적재된 {skipped}개 건너뜀, 신규 {len(fresh)}개만 처리")
        if not fresh:
            continue

        refined_data = refine(fresh)

        # refine은 일부 항목을 드롭할 수 있으므로 url로 원본 등록일을 다시 매핑.
        posted_by_url = {item["url"]: _parse_posted_date(item.get("date")) for item in fresh}

        for doc, assets, extra in refined_data:
            print(f'제목: {doc.title}')
            print(f'카테고리: {doc.category}')
            print(f'대상: {doc.target}')
            print(f'등록일: {posted_by_url.get(doc.url)}')
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
                posted_at=posted_by_url.get(doc.url),
            )
            insert_assets(doc.category, document_id, assets)

            chunks = embed_chunks(f"{doc.title}\n\n{doc.content}")
            insert_chunks(doc.category, document_id, chunks)
