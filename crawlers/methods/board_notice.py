import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from attachments import attachment_to_text, inline_image_to_text, xlsx_relevant

ASSETS_DIR = Path("crawl_result/assets")


@dataclass(frozen=True)
class BoardNoticeConfig:
    source_code: str
    source_name: str
    department: str | None
    base_url: str
    pages: int
    title_selector: str = ".view-title"
    date_selector: str = ".write dd"
    body_selector: str = ".view-con"
    attachment_selector: str = ".view-file li"
    row_selector: str = "tr:has(.td-subject a)"
    row_selector_after_first: str | None = None
    list_wait_selector: str = ".td-subject a"
    list_url: str | None = None
    list_url_template: str | None = None
    page_title_template: str | None = None
    dedupe_urls: bool = False


class BoardNoticeCrawler:
    KIND = "notice"

    def __init__(self, config: BoardNoticeConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

    def _abs(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        return urljoin(self.BASE_URL, url)

    def _save_image_asset(self, raw_bytes: bytes, mime) -> str:
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

    def _collect_attachments(self, detail_page) -> List[dict]:
        items = []
        lis = detail_page.locator(self.config.attachment_selector).all()
        for li in lis:
            dl = li.locator('a[href*="download.do"]').first
            try:
                filename = dl.inner_text().strip()
                download_url = self._abs(dl.get_attribute("href") or "")
            except Exception:
                continue
            preview_url = None
            prev = li.locator('a[href*="synapView.do"]')
            if prev.count() > 0:
                preview_url = self._abs(prev.first.get_attribute("href") or "")
            items.append({
                "filename": filename,
                "download_url": download_url,
                "preview_url": preview_url,
            })
        return items

    def _collect_inline_images(self, detail_page) -> List[str]:
        urls = []
        imgs = detail_page.locator(f"{self.config.body_selector} img").all()
        for img in imgs:
            src = img.get_attribute("src")
            if src:
                urls.append(self._abs(src))
        return urls

    def _goto_list_page(self, list_page, page_num: int) -> None:
        cfg = self.config
        if cfg.list_url_template:
            url = cfg.list_url_template.format(page=page_num)
            print(f"\n=== {page_num}페이지 수집: {url} ===")
            list_page.goto(url, wait_until="networkidle")
            return

        if page_num == 1:
            if not cfg.list_url:
                raise ValueError(f"{self.SOURCE_CODE}: list_url 또는 list_url_template이 필요합니다.")
            list_page.goto(cfg.list_url, wait_until="networkidle")
            return

        if not cfg.page_title_template:
            raise ValueError(f"{self.SOURCE_CODE}: page_title_template이 필요합니다.")
        list_page.get_by_title(cfg.page_title_template.format(page=page_num)).first.click()
        list_page.wait_for_load_state("networkidle")

    def _row_is_pinned(self, row) -> bool:
        try:
            class_name = row.get_attribute("class") or ""
            if "notice" in class_name.split():
                return True
        except Exception:
            pass
        try:
            first_cell = row.locator("td").first.inner_text().strip()
            return first_cell in {"공지", "알림"}
        except Exception:
            return False

    def _collect_post_records(self, list_page, page_num: int) -> List[dict]:
        row_selector = self.config.row_selector
        if page_num != 1 and self.config.row_selector_after_first:
            row_selector = self.config.row_selector_after_first

        records: List[dict] = []
        for row in list_page.locator(row_selector).all():
            try:
                href = row.locator(".td-subject a").first.get_attribute("href")
            except Exception:
                continue
            if href:
                records.append({
                    "url": self._abs(href),
                    "is_pinned": self._row_is_pinned(row),
                })
        return records

    def _collect_post_urls(self, list_page, page_num: int) -> List[str]:
        return [record["url"] for record in self._collect_post_records(list_page, page_num)]

    def collect_pinned_urls(self) -> set[str]:
        """현재 목록 첫 페이지의 고정 공지 URL 집합."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            try:
                self._goto_list_page(page, 1)
                page.wait_for_selector(self.config.list_wait_selector)
                return {
                    record["url"]
                    for record in self._collect_post_records(page, 1)
                    if record.get("is_pinned")
                }
            finally:
                browser.close()

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> Iterator[dict]:
        seen_urls: set[str] = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            list_page = context.new_page()
            detail_page = context.new_page()
            list_page.on("dialog", lambda dialog: dialog.accept())

            try:
                for page_num in range(1, self.config.pages + 1):
                    self._goto_list_page(list_page, page_num)
                    list_page.wait_for_selector(self.config.list_wait_selector)

                    post_records = self._collect_post_records(list_page, page_num)
                    if self.config.dedupe_urls:
                        new_records = [r for r in post_records if r["url"] not in seen_urls]
                        seen_urls.update(r["url"] for r in new_records)
                    else:
                        new_records = post_records

                    print(f"\n=== {page_num}페이지: 게시글 {len(post_records)}건, 처리 대상 {len(new_records)}건 ===")

                    if should_skip:
                        before = len(new_records)
                        new_records = [r for r in new_records if not should_skip(r["url"])]
                        print(f"     ↳ DB 중복 제외: {before - len(new_records)}건 스킵, {len(new_records)}건 처리")

                    for idx, record in enumerate(new_records, 1):
                        yield self._crawl_detail(
                            context,
                            detail_page,
                            record["url"],
                            idx,
                            len(new_records),
                            is_pinned=record.get("is_pinned", False),
                        )
            finally:
                browser.close()

    def _crawl_detail(self, context, detail_page, post_url: str, idx: int, total: int, is_pinned: bool = False) -> dict:
        print(f"[{idx}/{total}] {post_url} 접속 중...")
        detail_page.goto(post_url, wait_until="networkidle")

        try:
            title = detail_page.locator(self.config.title_selector).first.inner_text().strip()
        except Exception:
            title = "제목을 찾을 수 없음"

        try:
            date = detail_page.locator(self.config.date_selector).first.inner_text().strip()
        except Exception:
            date = "등록일을 찾을 수 없음"

        try:
            body_text = detail_page.locator(self.config.body_selector).first.inner_text().strip()
        except Exception:
            body_text = ""

        content_parts = [body_text] if body_text else []
        assets: List[dict] = []
        order = 0

        for img_url in self._collect_inline_images(detail_page):
            print(f"  - 본문 이미지 처리: {img_url}")
            txt, raw_bytes, mime = inline_image_to_text(img_url, context)
            if txt:
                content_parts.append(f"[본문 이미지]\n{txt}")
            if raw_bytes is not None:
                assets.append({
                    "kind": "inline_image",
                    "filename": None,
                    "source_url": img_url,
                    "storage_path": self._save_image_asset(raw_bytes, mime),
                    "mime_type": mime,
                    "extracted_text": txt,
                    "order_idx": order,
                })
                order += 1

        include_xlsx = True  # 현재는 모든 첨부파일을 텍스트로 변환해서 포함하도록 설정되어 있습니다.
        # xlsx_relevant(title, body_text) >> 만약 제목이나 본문에 '공고', '모집', '채용' 같은 단어가 있으면, 첨부된 엑셀 파일도 텍스트로 변환해서 내용에 포함할지 여부 판단하고 싶으면 이 함수를 활용할 수 있습니다. 
       
        for att in self._collect_attachments(detail_page):
            print(f"  - 첨부 처리: {att['filename']}")
            txt, meta = attachment_to_text(att, context, include_xlsx=include_xlsx)
            if txt:
                content_parts.append(txt)
            storage_path = None
            if meta.get("raw_bytes") is not None:
                storage_path = self._save_image_asset(meta["raw_bytes"], meta.get("mime_type"))
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

        return {
            "title": title,
            "date": date,
            "content": content,
            "url": post_url,
            "assets": assets,
            "is_pinned": is_pinned,
        }
