"""단건 URL ingest — 학생소식 1개 글만 크롤·파싱·DB 적재.

xlsx 첨부를 두 가지 포맷 중 하나로 재추출:
  --format schema   (기본) xlsx_to_text — [Schema] 라인 + 탭 구분 데이터
  --format prefixed         xlsx_to_text_prefixed — 행마다 헤더 prefix (토큰 비용 ~2x)

사용:
    docker compose exec app python scripts/ingest_one_url.py '<URL>' [--format schema|prefixed]
"""
import argparse
import logging
import sys
from pathlib import Path

# python scripts/ingest_one_url.py로 실행 시 sys.path[0]은 scripts/ 디렉터리라
# 프로젝트 루트의 모듈(attachments, db, ...)을 못 찾는다. 루트를 명시적으로 추가.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from attachments import _download, xlsx_to_text, xlsx_to_text_prefixed
from crawlers.sites.kongju import KONGJU_CRAWLERS
from refine import refine
from db import (
    upsert_source, insert_document, insert_assets, insert_chunks,
    document_exists, delete_document_by_url,
)
from embed import embed_chunks
from main import _parse_posted_date


def main(url: str, xlsx_format: str = "schema"):
    extractor = xlsx_to_text_prefixed if xlsx_format == "prefixed" else xlsx_to_text
    print(f"[config] xlsx_format={xlsx_format} → {extractor.__name__}")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    crawler = KONGJU_CRAWLERS["main_notice"]

    if document_exists(url):
        n = delete_document_by_url(url)
        print(f"🗑  기존 레코드 {n}건 삭제 후 재크롤 진행. url={url}")

    print("\n=== Playwright detail crawl 시작 ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        detail_page = context.new_page()
        try:
            item = crawler._crawl_detail(context, detail_page, url, 1, 1)

            # _crawl_detail은 키워드 미매치 xlsx를 다운로드조차 안 한다(extracted_text는
            # "(엑셀 첨부 — 임베딩 제외)" placeholder). 테스트 목적상 무조건 재다운로드 후
            # 프로덕션 xlsx_to_text(헤더 prefix 형식)로 재추출, item["content"]의
            # placeholder 블록을 swap한다.
            for a in item["assets"]:
                if a["kind"] != "attachment_xlsx":
                    continue
                filename = a["filename"]
                print(f"\n=== xlsx 재추출({extractor.__name__}): {filename} ===")
                try:
                    data = _download(a["source_url"], context)
                    new_text = extractor(data)
                except Exception as e:
                    print(f"  ⛔ 실패: {e}")
                    continue

                old_text = a.get("extracted_text") or ""
                label = f"[첨부: {filename}]"
                old_block = f"{label}\n{old_text}" if old_text else f"{label}\n(추출 텍스트 없음)"
                new_block = f"{label}\n{new_text}"
                if old_block in item["content"]:
                    item["content"] = item["content"].replace(old_block, new_block, 1)
                else:
                    # 본문에서 못 찾으면(예상 외 placeholder) 그냥 뒤에 덧붙임 — 테스트라 안전 우선
                    item["content"] += f"\n\n{new_block}"
                a["extracted_text"] = new_text
                print(f"  기존 길이={len(old_text)}자 → 신규={len(new_text)}자")
        finally:
            browser.close()

    print("\n=== 크롤 결과 요약 ===")
    print(f"title:   {item['title']}")
    print(f"date:    {item['date']}")
    print(f"url:     {item['url']}")
    print(f"content length: {len(item['content'])}")
    print(f"assets:  {len(item['assets'])}건")

    for i, a in enumerate(item["assets"]):
        print(f"\n--- asset[{i}] kind={a['kind']} filename={a.get('filename')!r} ---")
        text = a.get("extracted_text") or ""
        if a["kind"] == "attachment_xlsx":
            print("  ↓↓↓ xlsx_to_text() 전체 출력 ↓↓↓")
            print(text)
            print("  ↑↑↑ xlsx_to_text() 끝 ↑↑↑")
        else:
            preview = text if len(text) <= 800 else text[:800] + f"... (총 {len(text)}자)"
            print(preview)

    print("\n=== refine (LLM 메타 분류) ===")
    refined = refine([item])
    if not refined:
        print("⛔ refine 결과 비어있음 — 종료")
        return
    doc, assets, extra = refined[0]
    print(f"category: {doc.category}")
    print(f"target:   {doc.target}")
    print(f"keywords: {doc.keywords}")
    print(f"start_date / end_date: {doc.start_date} / {doc.end_date}")

    print("\n=== DB 적재 ===")
    source_id = upsert_source(
        code=crawler.SOURCE_CODE,
        name=crawler.SOURCE_NAME,
        kind=crawler.KIND,
        department=crawler.DEPARTMENT,
        base_url=crawler.BASE_URL,
    )
    posted_at = _parse_posted_date(item.get("date"))
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

    print(f"\n✅ 완료 — category={doc.category} document_id={document_id} chunks={len(chunks)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="단건 URL ingest")
    p.add_argument("url", help="크롤할 게시글 URL")
    p.add_argument(
        "--format", choices=["schema", "prefixed"], default="prefixed",
        help="xlsx 추출 포맷 (기본 prefixed — 프로덕션과 일치)",
    )
    args = p.parse_args()
    main(args.url, args.format)
