"""컴퓨터공학과 학과공지 게시판 크롤러.

CLAUDE.md §3/§4 컨벤션 준수. SubPortal CMS의 `?page=N` GET이 통하므로
페이지 순회는 직접 URL 변경. 첨부/이미지 처리는 attachments.py 재사용.
고정글(tr.notice)도 포함하되 페이지마다 반복되므로 URL set으로 dedup.
"""

import hashlib
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from attachments import attachment_to_text, inline_image_to_text, xlsx_relevant

SOURCE_CODE = "cse_notice"
SOURCE_NAME = "컴퓨터공학과 학과공지"
DEPARTMENT = "컴퓨터공학과"
KIND = "notice"
BASE_URL = "https://computer.kongju.ac.kr"

LIST_URL = "https://computer.kongju.ac.kr/bbs/ZD1140/1410/artclList.do?page={page}"
PAGES = 5

ASSETS_DIR = Path("crawl_result/assets")


def _abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return urljoin(BASE_URL, url)


def _save_image_asset(raw_bytes: bytes, mime) -> str:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(raw_bytes).hexdigest()
    if mime == "image/png":
        ext = ".png"
    elif mime == "image/gif":
        ext = ".gif"
    else:
        ext = ".jpg"
    path = ASSETS_DIR / f"{digest}{ext}"
    if not path.exists():
        path.write_bytes(raw_bytes)
    return str(path)


def _collect_attachments(detail_page) -> List[dict]:
    items = []
    lis = detail_page.locator(".view-file li").all()
    for li in lis:
        dl = li.locator('a[href*="download.do"]').first
        try:
            filename = dl.inner_text().strip()
            download_url = _abs(dl.get_attribute("href") or "")
        except Exception:
            continue
        preview_url = None
        prev = li.locator('a[href*="synapView.do"]')
        if prev.count() > 0:
            preview_url = _abs(prev.first.get_attribute("href") or "")
        items.append({
            "filename": filename,
            "download_url": download_url,
            "preview_url": preview_url,
        })
    return items


def _collect_inline_images(detail_page) -> List[str]:
    urls = []
    imgs = detail_page.locator(".view-con img").all()
    for img in imgs:
        src = img.get_attribute("src")
        if src:
            urls.append(_abs(src))
    return urls


def _collect_post_urls(list_page) -> List[str]:
    """고정글(tr.notice) + 일반글(tr) 모두에서 글 URL 수집."""
    rows = list_page.locator(".board-table tbody tr").all()
    urls: List[str] = []
    for row in rows:
        link = row.locator(".td-subject a").first
        try:
            href = link.get_attribute("href")
        except Exception:
            continue
        if href:
            urls.append(_abs(href))
    return urls


def crawling(should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """should_skip(url): True면 그 글의 상세 진입·첨부 OCR 모두 건너뜀.
    main.py가 db.document_exists를 주입해 DB에 이미 있는 글을 미리 차단한다.
    """
    crawled_data: List[dict] = []
    seen_urls: set[str] = set()  # 고정글이 페이지마다 반복 노출 → 중복 처리 방지

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        list_page = context.new_page()
        detail_page = context.new_page()
        list_page.on("dialog", lambda dialog: dialog.accept())

        for page_num in range(1, PAGES + 1):
            url = LIST_URL.format(page=page_num)
            print(f"\n=== {page_num}페이지 수집: {url} ===")
            list_page.goto(url, wait_until="networkidle")
            list_page.wait_for_selector(".board-table tbody tr")

            post_urls = _collect_post_urls(list_page)
            new_urls = [u for u in post_urls if u not in seen_urls]
            seen_urls.update(new_urls)
            print(f"  → 게시글 {len(post_urls)}건 (신규 {len(new_urls)}건)")

            if should_skip:
                before = len(new_urls)
                new_urls = [u for u in new_urls if not should_skip(u)]
                print(f"     ↳ DB 중복 제외: {before - len(new_urls)}건 스킵, {len(new_urls)}건 처리")

            for j, post_url in enumerate(new_urls, 1):
                print(f"[{j}/{len(new_urls)}] {post_url} 접속 중...")
                detail_page.goto(post_url, wait_until="networkidle")

                try:
                    title = detail_page.locator(".view-title").first.inner_text().strip()
                except Exception:
                    title = "제목을 찾을 수 없음"

                try:
                    date = detail_page.locator("dl.write dd").first.inner_text().strip()
                except Exception:
                    date = ""

                try:
                    body_text = detail_page.locator(".view-con").first.inner_text().strip()
                except Exception:
                    body_text = ""

                inline_imgs = _collect_inline_images(detail_page)
                attachments = _collect_attachments(detail_page)

                content_parts = []
                assets: List[dict] = []
                order = 0

                if body_text:
                    content_parts.append(body_text)

                for img_url in inline_imgs:
                    print(f"  - 본문 이미지 처리: {img_url}")
                    txt, raw_bytes, mime = inline_image_to_text(img_url, context)
                    if txt:
                        content_parts.append(f"[본문 이미지]\n{txt}")
                    if raw_bytes is not None:
                        storage_path = _save_image_asset(raw_bytes, mime)
                        assets.append({
                            "kind": "inline_image",
                            "filename": None,
                            "source_url": img_url,
                            "storage_path": storage_path,
                            "mime_type": mime,
                            "extracted_text": txt,
                            "order_idx": order,
                        })
                        order += 1

                # 수강신청·교양·편성 등 키워드가 제목/본문에 있으면 XLSX도 본문 추출 (검색 대상에 포함)
                include_xlsx = xlsx_relevant(title, body_text)
                for att in attachments:
                    print(f"  - 첨부 처리: {att['filename']}")
                    txt, meta = attachment_to_text(att, context, include_xlsx=include_xlsx)
                    if txt:
                        content_parts.append(txt)
                    if meta.get("raw_bytes") is not None:
                        storage_path = _save_image_asset(meta["raw_bytes"], meta.get("mime_type"))
                    else:
                        storage_path = None
                    assets.append({
                        "kind": meta["kind"],
                        "filename": meta["filename"],
                        "source_url": meta["source_url"],
                        "storage_path": storage_path,
                        "mime_type": meta.get("mime_type"),
                        "extracted_text": meta.get("extracted_text", ""),
                        "order_idx": order,
                    })
                    order += 1

                content = "\n\n".join(content_parts) if content_parts else "내용을 찾을 수 없음"

                print(title)
                print(date)
                print(content[:200] + ("..." if len(content) > 200 else ""))

                crawled_data.append({
                    "title": title,
                    "date": date,
                    "content": content,
                    "url": post_url,
                    "assets": assets,
                })

        return crawled_data
