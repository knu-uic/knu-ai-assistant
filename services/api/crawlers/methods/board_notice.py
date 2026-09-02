import hashlib
import math
import queue
import ssl
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from playwright.sync_api import sync_playwright
from urllib3.util import create_urllib3_context

from config import (
    ATTACHMENT_DOWNLOAD_BACKOFF_SECONDS,
    ATTACHMENT_DOWNLOAD_RETRY_ATTEMPTS,
    CRAWL_HTTP_BACKOFF_SECONDS,
    CRAWL_HTTP_MAX_ATTEMPTS,
    CRAWL_HTTP_TIMEOUT_SECONDS,
    MAX_CRAWL_WORKERS,
)
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
    max_workers: int | None = None
    min_success_ratio: float = 0.5
    min_success_count: int = 3


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


class _RequestsApiResponse:
    """Small Playwright APIResponse-compatible wrapper for attachment adapters."""

    def __init__(self, response: requests.Response):
        self._response = response
        self.ok = response.ok
        self.status = response.status_code

    def body(self) -> bytes:
        return self._response.content


class _RequestsDownloadContext:
    """Expose the crawler's retrying HTTP session through context.request.get()."""

    def __init__(self, crawler: "BoardNoticeCrawler"):
        self.crawler = crawler
        self.request = self

    def get(self, url: str, timeout: int, fail_on_status_code: bool = False):
        del fail_on_status_code
        response = self.crawler._fetch_response(
            url,
            timeout_seconds=max(1, math.ceil(timeout / 1000)),
            attempts=ATTACHMENT_DOWNLOAD_RETRY_ATTEMPTS,
            backoff_seconds=ATTACHMENT_DOWNLOAD_BACKOFF_SECONDS,
        )
        return _RequestsApiResponse(response)


class _ReusableBrowserContext:
    """Lazily own one Chromium context on a dedicated thread and reuse it."""

    def __init__(self):
        self._tasks: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_error: Exception | None = None

    def _ensure_started(self) -> None:
        if self._thread is not None:
            if self._startup_error is not None:
                raise self._startup_error
            if not self._thread.is_alive():
                raise RuntimeError("crawler Chromium worker stopped unexpectedly")
            return
        self._thread = threading.Thread(
            target=self._worker,
            name="knu-crawler-browser",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            raise self._startup_error

    def _worker(self) -> None:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                self._ready.set()
                try:
                    while True:
                        task = self._tasks.get()
                        if task is None:
                            return
                        callback, future = task
                        try:
                            future.set_result(callback(context))
                        except Exception as error:
                            future.set_exception(error)
                finally:
                    browser.close()
        except Exception as error:
            self._startup_error = error
            self._ready.set()

    def run(self, callback: Callable):
        self._ensure_started()
        future: Future = Future()
        self._tasks.put((callback, future))
        return future.result()

    def close(self) -> None:
        if self._thread is None:
            return
        self._tasks.put(None)
        self._thread.join(timeout=30)
        self._thread = None


class BoardNoticeCrawler:
    KIND = "notice"

    def __init__(self, config: BoardNoticeConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url
        self._session_local = threading.local()
        self._sleep = time.sleep
        self._browser_context_factory = _ReusableBrowserContext
        self.last_run_stats = {
            "discovered": 0,
            "known": 0,
            "succeeded": 0,
            "failed": 0,
            "accepted_pages": 0,
            "rejected_pages": 0,
        }

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.mount("https://", CustomSSLContextAdapter())
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            )
        })
        return session

    def _session(self) -> requests.Session:
        session = getattr(self._session_local, "value", None)
        if session is None:
            session = self._new_session()
            self._session_local.value = session
        return session

    def _fetch_response(
        self,
        url: str,
        *,
        timeout_seconds: int = CRAWL_HTTP_TIMEOUT_SECONDS,
        attempts: int = CRAWL_HTTP_MAX_ATTEMPTS,
        backoff_seconds: int = CRAWL_HTTP_BACKOFF_SECONDS,
    ) -> requests.Response:
        attempts = max(1, attempts)
        retry_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._session().get(url, timeout=timeout_seconds)
                if response.status_code not in retry_statuses:
                    response.raise_for_status()
                    return response
                last_error = requests.HTTPError(
                    f"retryable HTTP {response.status_code} for {url}",
                    response=response,
                )
                response.close()
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
            if attempt >= attempts:
                break
            delay = backoff_seconds * (3 ** (attempt - 1))
            print(
                f"  ↻ HTTP 재시도 {attempt + 1}/{attempts}: "
                f"{url} ({type(last_error).__name__}), {delay}초 후"
            )
            self._sleep(delay)
        assert last_error is not None
        raise last_error

    def _abs(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        return urljoin(self.BASE_URL, url)

    def _fetch_html(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._fetch_response(url).text, "html.parser")

    def _fetch_html_text(self, url: str) -> str:
        return self._fetch_response(url).text

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

    def _collect_attachments(self, soup: BeautifulSoup) -> list[dict]:
        items: list[dict] = []
        for li in soup.select(self.config.attachment_selector):
            dl = li.select_one('a[href*="download.do"]')
            if dl is None:
                continue
            filename = dl.get_text(" ", strip=True)
            download_url = self._abs(dl.get("href") or "")
            preview_url = None
            prev = li.select_one('a[href*="synapView.do"]')
            if prev is not None:
                preview_url = self._abs(prev.get("href") or "")
            items.append({
                "filename": filename,
                "download_url": download_url,
                "preview_url": preview_url,
            })
        return items

    def _collect_inline_images(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for img in soup.select(f"{self.config.body_selector} img"):
            src = img.get("src")
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
        self.last_run_stats = {
            "discovered": 0,
            "known": 0,
            "succeeded": 0,
            "failed": 0,
            "accepted_pages": 0,
            "rejected_pages": 0,
        }
        browser_context = self._browser_context_factory()
        try:
            for page_num in range(1, self.config.pages + 1):
                post_records = self._collect_post_records(None, page_num)

                if self.config.dedupe_urls:
                    new_records = [
                        record for record in post_records
                        if record["url"] not in seen_urls
                    ]
                    seen_urls.update(record["url"] for record in new_records)
                else:
                    new_records = post_records

                discovered = len(new_records)
                self.last_run_stats["discovered"] += discovered
                print(
                    f"\n=== {page_num}페이지: 게시글 {len(post_records)}건, "
                    f"처리 대상 {discovered}건 ==="
                )

                known_count = 0
                if should_skip:
                    filtered_records = []
                    for record in new_records:
                        if should_skip(record["url"]):
                            known_count += 1
                        else:
                            filtered_records.append(record)
                    new_records = filtered_records
                    self.last_run_stats["known"] += known_count
                    print(
                        f"     ↳ DB 중복 제외: {known_count}건 확인, "
                        f"{len(new_records)}건 신규 처리"
                    )

                page_results: list[dict] = []
                workers = max(1, self.config.max_workers or MAX_CRAWL_WORKERS)
                if new_records:
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        futures = {
                            executor.submit(
                                self._crawl_post_parallel,
                                browser_context,
                                record["url"],
                                idx,
                                len(new_records),
                                is_pinned=record.get("is_pinned", False),
                            ): record["url"]
                            for idx, record in enumerate(new_records, 1)
                        }
                        for future in as_completed(futures):
                            result = future.result()
                            if result is not None:
                                page_results.append(result)

                succeeded = len(page_results)
                failed = len(new_records) - succeeded
                self.last_run_stats["succeeded"] += succeeded
                self.last_run_stats["failed"] += failed
                required = min(
                    discovered,
                    max(
                        self.config.min_success_count,
                        math.ceil(discovered * self.config.min_success_ratio),
                    ),
                )
                evidence_count = known_count + succeeded
                if evidence_count < required:
                    self.last_run_stats["rejected_pages"] += 1
                    print(
                        f"  ⚠️ {page_num}페이지 결과 보류: 확인 {evidence_count}/{discovered}건, "
                        f"최소 {required}건 필요. 성공 항목도 다음 실행에서 재시도합니다."
                    )
                    break

                self.last_run_stats["accepted_pages"] += 1
                yield from page_results

                if discovered > 0 and known_count == discovered:
                    print("     ↳ 현재 페이지가 모두 적재되어 있어 이전 페이지 수집을 종료합니다.")
                    break
        finally:
            browser_context.close()

    def _crawl_post_parallel(
        self,
        browser_context: _ReusableBrowserContext,
        post_url: str,
        idx: int,
        total: int,
        is_pinned: bool = False,
    ) -> dict | None:
        """Collect one post over retrying HTTP; Chromium is lazy and shared."""
        try:
            return self._crawl_detail_internal(
                browser_context,
                post_url,
                idx,
                total,
                is_pinned=is_pinned,
            )
        except Exception as error:
            print(
                f"  ⚠️ [{idx}/{total}] {post_url} 수집 중 예외 발생 (스킵함): "
                f"{type(error).__name__}: {error}"
            )
            return None

    def crawl_detail(self, post_url: str, *, is_pinned: bool = False) -> dict:
        """Collect one detail URL while preserving lazy reusable-browser behavior."""
        browser_context = self._browser_context_factory()
        try:
            return self._crawl_detail_internal(
                browser_context,
                post_url,
                1,
                1,
                is_pinned=is_pinned,
            )
        finally:
            browser_context.close()

    def _crawl_detail_internal(
        self,
        browser_context: _ReusableBrowserContext,
        post_url: str,
        idx: int,
        total: int,
        is_pinned: bool = False,
    ) -> dict:
        print(f"[{idx}/{total}] {post_url} 접속 중...")
        html = self._fetch_html_text(post_url)
        soup = BeautifulSoup(html, "html.parser")
        http_context = _RequestsDownloadContext(self)

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

        for img_url in self._collect_inline_images(soup):
            print(f"  - 본문 이미지 처리: {img_url}")
            txt, raw_bytes, mime = inline_image_to_text(img_url, http_context)

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
       
        for att in self._collect_attachments(soup):
            print(f"  - 첨부 처리: {att['filename']}")

            filename_lower = att["filename"].lower()
            preview_url = att.get("preview_url")

            # 공주대 요람 같은 대형 HWP는
            # download.do 대신 synap viewer 자체를 직접 스크롤 수집한다.
            # (synap 미리보기는 HWP 전용 — HWPX는 attachment_to_text에서 XML 추출로 처리)
            if preview_url and filename_lower.endswith(".hwp"):
                try:
                    viewer_text = browser_context.run(
                        lambda context: hwp_via_preview(preview_url, context)
                    )

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

            txt, meta = attachment_to_text(
                {**att, "preview_url": None},
                http_context,
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
