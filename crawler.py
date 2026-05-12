import hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
from typing import List
from urllib.parse import urljoin

from attachments import attachment_to_text, inline_image_to_text

BASE = "https://www.kongju.ac.kr"
ASSETS_DIR = Path("crawl_result/assets")


def _abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return urljoin(BASE, url)


def _save_image_asset(raw_bytes: bytes, mime) -> str:
    """이미지 bytes를 crawl_result/assets/<sha1>.<ext>에 저장하고 경로를 돌려준다."""
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


def crawling() -> List[dict]:
    crawled_data: List[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        list_page = context.new_page()
        detail_page = context.new_page()

        list_page.on("dialog", lambda dialog: dialog.accept())
        url = "https://www.kongju.ac.kr/KNU/16909/subview.do"
        list_page.goto(url, wait_until="networkidle")

        for page_num in range(1, 3):
            if page_num != 1:
                list_page.get_by_title(f"{page_num}페이지").first.click()
                list_page.wait_for_load_state("networkidle")

            list_page.wait_for_selector(".td-subject a")
            row_selector = (
                "tr:has(.td-subject a)"
                if page_num == 1
                else "tr:not(.notice):has(.td-subject a)"
            )
            rows = list_page.locator(row_selector).all()

            post_urls = []
            for row in rows:
                href = row.locator(".td-subject a").first.get_attribute("href")
                if href:
                    post_urls.append(_abs(href))

            print(f"\n=== {page_num}페이지: 총 {len(post_urls)}개의 게시글 링크 수집 완료 ===")

            for j, post_url in enumerate(post_urls):
                print(f"[{j+1}/{len(post_urls)}] {post_url} 접속 중...")
                detail_page.goto(post_url, wait_until="networkidle")

                try:
                    title = detail_page.locator(".view-title").first.inner_text().strip()
                except Exception:
                    title = "제목을 찾을 수 없음"

                try:
                    date = detail_page.locator(".write dd").first.inner_text().strip()
                except Exception:
                    date = "등록일을 찾을 수 없음"

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

                for att in attachments:
                    print(f"  - 첨부 처리: {att['filename']}")
                    txt, meta = attachment_to_text(att, context)
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
                print(content[:300] + ("..." if len(content) > 300 else ""))

                crawled_data.append({
                    "title": title,
                    "date": date,
                    "content": content,
                    "url": post_url,
                    "assets": assets,
                })

        return crawled_data