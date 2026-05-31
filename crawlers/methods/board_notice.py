import hashlib
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from playwright.sync_api import sync_playwright
from urllib3.util import create_urllib3_context

from config import MAX_CRAWL_WORKERS
from extractors.attachments import (
    attachment_to_text,
    hwp_via_preview,
    inline_image_to_text,
    xlsx_relevant,
)

ASSETS_DIR = Path("data/assets")


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
    wait_until: str = "networkidle"


class CustomSSLContextAdapter(requests.adapters.HTTPAdapter):
    """구버전 TLS/SSL(SECLEVEL=1)을 허용하도록 urllib3의 SSLContext를 커스텀하는 어댑터."""
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().proxy_manager_for(*args, **kwargs)


class BoardNoticeCrawler:
    KIND = "notice"

    def __init__(self, config: BoardNoticeConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

        self.session = requests.Session()
        self.session.mount("https://", CustomSSLContextAdapter())
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            )
        })

    def _abs(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        return urljoin(self.BASE_URL, url)

    def _fetch_html(self, url: str) -> BeautifulSoup:
        res = self.session.get(url, timeout=30)
        res.raise_for_status()
        return BeautifulSoup(res.text, "html.parser")

    def _fetch_html_text(self, url: str) -> str:
        res = self.session.get(url, timeout=30)
        res.raise_for_status()
        return res.text

    def _text_from_selector(self, soup: BeautifulSoup, selector: str) -> str:
        node = soup.select_one(selector)
        if not node:
            return ""
        return node.get_text("\n", strip=True)

    def _save_image_asset(
        self,
        raw_bytes: bytes,
        mime: str | None,
    ) -> str:
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

    def _collect_attachments(self, detail_page) -> list[dict]:
        items: list[dict] = []
        lis = detail_page.locator(self.config.attachment_selector).all()
        for li in lis:
            li_index = len(items)
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
                "attachment_index": li_index,
                "attachment_selector": self.config.attachment_selector,
            })
        return items

    def _collect_inline_images(self, detail_page) -> list[str]:
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
            list_page.goto(url, wait_until=cfg.wait_until)
            return

        if page_num == 1:
            if not cfg.list_url:
                raise ValueError(f"{self.SOURCE_CODE}: list_url 또는 list_url_template이 필요합니다.")
            list_page.goto(cfg.list_url, wait_until=cfg.wait_until)
            return

        if not cfg.page_title_template:
            raise ValueError(f"{self.SOURCE_CODE}: page_title_template이 필요합니다.")
        list_page.get_by_title(cfg.page_title_template.format(page=page_num)).first.click()
        list_page.wait_for_load_state(cfg.wait_until)

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

    def _collect_post_records(self, list_page, page_num: int) -> list[dict]:
        if self.config.list_url_template:
            url = self.config.list_url_template.format(page=page_num)
        elif page_num == 1:
            url = self.config.list_url or self.BASE_URL
        else:
            raise ValueError(
                f"{self.SOURCE_CODE}: list_url_template 설정이 필요합니다."
            )

        soup = self._fetch_html(url)

        records: list[dict] = []

        for row in soup.select("tr"):
            anchor = row.select_one(".td-subject a")
            if not anchor:
                continue

            href = anchor.get("href")
            if not href:
                continue

            class_names = row.get("class", [])
            first_td = row.select_one("td")
            first_text = first_td.get_text(strip=True) if first_td else ""

            is_pinned = (
                "notice" in class_names
                or first_text in {"공지", "알림"}
            )

            records.append({
                "url": self._abs(href),
                "is_pinned": is_pinned,
            })

        return records

    def _collect_post_urls(self, list_page, page_num: int) -> list[str]:
        return [record["url"] for record in self._collect_post_records(list_page, page_num)]

    def collect_pinned_urls(self) -> set[str]:
        """현재 목록 첫 페이지의 고정 공지 URL 집합."""
        return {
            record["url"]
            for record in self._collect_post_records(None, 1)
            if record.get("is_pinned")
        }

    def crawling(
        self,
        should_skip: Callable[[str], bool] | None = None,
    ) -> Iterator[dict]:
        seen_urls: set[str] = set()
        consecutive_skips = 0
        max_consecutive_skips = 1

        for page_num in range(1, self.config.pages + 1):
            post_records = self._collect_post_records(None, page_num)

            if self.config.dedupe_urls:
                new_records = [
                    r for r in post_records
                    if r["url"] not in seen_urls
                ]
                seen_urls.update(r["url"] for r in new_records)
            else:
                new_records = post_records

            print(
                f"\n=== {page_num}페이지: 게시글 {len(post_records)}건, 처리 대상 {len(new_records)}건 ==="
            )

            if should_skip:
                filtered_records = []
                skipped_in_page = 0

                for r in new_records:
                    if should_skip(r["url"]):
                        skipped_in_page += 1
                        consecutive_skips += 1
                    else:
                        consecutive_skips = 0
                        filtered_records.append(r)

                new_records = filtered_records

                print(
                    f"     ↳ DB 중복 제외: {skipped_in_page}건 스킵, {len(new_records)}건 처리"
                )

                if consecutive_skips >= max_consecutive_skips:
                    print(
                        f"     ↳ 연속 중복 {consecutive_skips}건 발견 — 크롤링 조기 종료"
                    )
                    return

            if not new_records:
                continue

            with ThreadPoolExecutor(max_workers=MAX_CRAWL_WORKERS) as executor:
                futures = {
                    executor.submit(
                        self._crawl_post_parallel,
                        record["url"],
                        idx,
                        len(new_records),
                        is_pinned=record.get("is_pinned", False),
                    ): record["url"]
                    for idx, record in enumerate(new_records, 1)
                }

                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            yield result
                    except Exception as e:
                        print(f"  ❌ [{url}] 스레드 처리 중 잡히지 않은 예외 발생: {type(e).__name__}: {e}")

    def _crawl_post_parallel(self, post_url: str, idx: int, total: int, is_pinned: bool = False) -> dict | None:
        """스레드별로 독립된 Playwright 인스턴스를 실행하여 상세 게시글을 안전하게 크롤링합니다.
        예외가 발생할 경우 이를 격리(catch)하여 로그를 남기고 None을 리턴하여 다른 스레드에 영향이 없도록 합니다.
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                detail_page = context.new_page()
                try:
                    result = self._crawl_detail_internal(
                        context,
                        detail_page,
                        post_url,
                        idx,
                        total,
                        is_pinned=is_pinned,
                    )
                    return result
                finally:
                    browser.close()
        except Exception as e:
            print(f"  ⚠️ [{idx}/{total}] {post_url} 병렬 수집 중 예외 발생 (스킵함): {type(e).__name__}: {e}")
            return None

    def _crawl_detail_internal(self, context, detail_page, post_url: str, idx: int, total: int, is_pinned: bool = False) -> dict:
        print(f"[{idx}/{total}] {post_url} 접속 중...")
        html = self._fetch_html_text(post_url)
        soup = BeautifulSoup(html, "html.parser")

        # 첨부 다운로드 / synap viewer / inline image OCR 용도로만 playwright 사용
        detail_page.goto(post_url, wait_until="domcontentloaded")

        title = self._text_from_selector(
            soup,
            self.config.title_selector,
        ) or "제목을 찾을 수 없음"

        date = self._text_from_selector(
            soup,
            self.config.date_selector,
        ) or "등록일을 찾을 수 없음"

        body_text = self._text_from_selector(
            soup,
            self.config.body_selector,
        )

        # body는 별도 저장
        body_content = body_text.strip() if body_text else ""

        # attachment text는 별도 저장
        attachment_contents: list[dict] = []
        attachment_names: list[str] = []

        # legacy full content 유지
        content_parts = [body_content] if body_content else []

        assets: list[dict] = []
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

            filename_lower = att["filename"].lower()
            preview_url = att.get("preview_url")

            # 공주대 요람 같은 대형 HWP/HWPX는
            # download.do 대신 synap viewer 자체를 직접 스크롤 수집한다.
            if preview_url and filename_lower.endswith((".hwp", ".hwpx")):
                try:
                    viewer_text = hwp_via_preview(preview_url, context)

                    if viewer_text and viewer_text.strip():
                        attachment_names.append(att["filename"])

                        attachment_contents.append({
                            "name": att["filename"],
                            "text": viewer_text,
                            "type": "attachment_hwpx_preview",
                        })

                        content_parts.append(
                            f"[첨부: {att['filename']}]\n{viewer_text}"
                        )

                        assets.append({
                            "kind": "attachment_hwpx_preview",
                            "filename": att["filename"],
                            "source_url": preview_url,
                            "storage_path": None,
                            "mime_type": "text/plain",
                            "extracted_text": viewer_text,
                            "order_idx": order,
                        })

                        order += 1
                        continue

                except Exception as e:
                    print(f"  - synap viewer 수집 실패: {e}")

            att["detail_page"] = detail_page

            txt, meta = attachment_to_text(
                att,
                context,
                include_xlsx=include_xlsx,
            )

            if txt:
                attachment_names.append(att["filename"])

                attachment_contents.append({
                    "name": att["filename"],
                    "text": txt,
                    "type": meta.get("kind", "attachment"),
                })
                # Do not append attachment OCR to legacy content_parts to avoid duplicate retrieval contamination.

            storage_path = None

            if meta.get("raw_bytes") is not None:
                storage_path = self._save_image_asset(
                    meta["raw_bytes"],
                    meta.get("mime_type"),
                )

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

        content = (
            "\n\n".join(
                part.strip()
                for part in content_parts
                if part and part.strip()
            )
            if content_parts
            else "내용을 찾을 수 없음"
        )
        print(title)
        print(date)
        print(content[:300] + ("..." if len(content) > 300 else ""))

        return {
            "title": title,
            "date": date,
            "content": content,

            # 신규 구조
            "body_content": body_content,
            "attachment_names": attachment_names,
            "attachment_contents": attachment_contents,

            "url": post_url,
            "assets": assets,
            "is_pinned": is_pinned,
        }
