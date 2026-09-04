import hashlib
import math
import queue
import re
import ssl
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

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
    inline_image_to_text,
    xlsx_relevant,
)

ASSETS_DIR = Path("data/assets")
_BODY_BLOCK_TAGS = {
    "address", "article", "blockquote", "div", "fieldset", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "thead", "tfoot", "tr", "ul",
}


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
    dedupe_urls: bool = True
    wait_until: str = "networkidle"
    max_workers: int | None = None
    min_success_ratio: float = 0.5
    min_success_count: int = 3


@dataclass(frozen=True)
class CrawlPageScope:
    """게시판 목록을 어디까지 확인할지 정의한다."""

    mode: str = "configured"
    start_page: int = 1
    end_page: int | None = None
    recent_days: int = 7


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
        absolute = url if url.startswith("http") else urljoin(self.BASE_URL, url)
        parsed = urlsplit(absolute)
        # K2Web의 게시글 고정 경로는 query가 없어도 동일하다. CSRF나
        # 목록 이동 파라미터로 같은 공지가 다른 URL로 저장되는 것을 막는다.
        if parsed.path.endswith("/artclView.do"):
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    def _fetch_html(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._fetch_response(url).text, "html.parser")

    def _fetch_html_text(self, url: str) -> str:
        return self._fetch_response(url).text

    def _text_from_selector(self, soup: BeautifulSoup, selector: str) -> str:
        node = soup.select_one(selector)
        if not node:
            return ""
        return node.get_text("\n", strip=True)

    def _body_from_selector(self, soup: BeautifulSoup, selector: str) -> str:
        """본문 HTML을 block-aware Markdown 텍스트로 바꾼다.

        K2Web 편집기는 한 문장을 여러 span으로 잘게 나누기도 한다. 모든 text node
        사이에 줄바꿈을 넣으면 단어까지 갈라지므로, div/p/br 같은 실제 block 경계만
        줄바꿈으로 보존한다. 링크는 RAG와 Manager 양쪽에서 목적지를 잃지 않도록
        Markdown 링크로 남긴다.
        """
        node = soup.select_one(selector)
        if node is None:
            node = soup.select_one(".view-con, .artclView, .board-view-content, .view-content")
        if node is None:
            return ""

        inline_number = 0
        inline_sources: set[str] = set()

        def render(current) -> str:
            nonlocal inline_number
            if isinstance(current, NavigableString):
                return re.sub(r"[\s\u00a0]+", " ", str(current))
            if not isinstance(current, Tag):
                return ""
            name = current.name.lower()
            if name in {"script", "style", "noscript"}:
                return ""
            if name == "br":
                return "\n"
            if name == "img" and current.get("src"):
                source = self._abs(str(current.get("src") or "").strip())
                if not source or source in inline_sources:
                    return ""
                inline_sources.add(source)
                inline_number += 1
                return f"\n[본문 그림 {inline_number}]\n"
            if name == "a":
                label = "".join(render(child) for child in current.children).strip()
                url = self._abs(str(current.get("href") or "").strip())
                if not label:
                    label = url
                # K2Web 작성기가 앞선의 href를 이메일·구분선에 잘못
                # 복사한 사례는 클릭 가능한 것처럼 변환하지 않는다.
                if re.fullmatch(r"[^0-9A-Za-z가-힣]+", label):
                    return label
                if re.fullmatch(r"[^@\s]+@[^@\s]+", label) and not url.startswith("mailto:"):
                    return label
                if url.startswith(("http://", "https://")):
                    return url if label == url else f"[{label}]({url})"
                return label
            if name in {"td", "th"}:
                return "".join(render(child) for child in current.children).strip() + " | "

            content = "".join(render(child) for child in current.children)
            if name == "li":
                content = content.strip()
                prefix = "" if re.match(r"^[-*•◆※★]", content) else "- "
                return f"\n{prefix}{content}\n"
            if name in _BODY_BLOCK_TAGS:
                return f"\n{content.strip()}\n"
            return content

        text = render(node).replace("\r", "")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

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
        elif mime == "image/webp":
            ext = ".webp"
        elif mime == "image/bmp":
            ext = ".bmp"
        else:
            ext = ".jpg"
        path = ASSETS_DIR / f"{digest}{ext}"
        if not path.exists():
            path.write_bytes(raw_bytes)
        return str(path)

    def _save_attachment_asset(self, raw_bytes: bytes, filename: str) -> str:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(raw_bytes).hexdigest()
        ext = Path(filename).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
            ext = ".bin"
        path = ASSETS_DIR / f"{digest}{ext}"
        if not path.exists():
            path.write_bytes(raw_bytes)
        return str(path)

    def _collect_attachments(self, soup: BeautifulSoup) -> list[dict]:
        items: list[dict] = []
        roots = soup.select(self.config.attachment_selector)
        anchors = []
        for root in roots:
            if root.name == "a" and "download.do" in str(root.get("href") or ""):
                anchors.append(root)
            anchors.extend(root.select('a[href*="download.do"]'))
        if not anchors:
            anchors = soup.select('.view-file a[href*="download.do"], a.artclFile[href*="download.do"]')
        seen: set[str] = set()
        for dl in anchors:
            filename = dl.get_text(" ", strip=True)
            download_url = self._abs(dl.get("href") or "")
            if not download_url or download_url in seen:
                continue
            seen.add(download_url)
            preview_url = None
            container = dl.find_parent("li") or dl.parent
            prev = container.select_one('a[href*="synapView.do"]') if container else None
            if prev is not None:
                preview_url = self._abs(prev.get("href") or "")
            items.append({
                "filename": filename,
                "download_url": download_url,
                "preview_url": preview_url,
            })
        return items

    def _collect_inline_images(self, soup: BeautifulSoup) -> list[dict]:
        node = soup.select_one(self.config.body_selector)
        if node is None:
            node = soup.select_one(".view-con, .artclView, .board-view-content, .view-content")
        if node is None:
            return []
        images = []
        seen: set[str] = set()
        for img in node.select("img"):
            src = str(img.get("src") or "").strip()
            if not src:
                continue
            url = self._abs(src)
            if not url or url in seen:
                continue
            seen.add(url)
            number = len(images) + 1
            images.append({
                "number": number,
                "marker": f"[본문 그림 {number}]",
                "url": url,
                "alt": str(img.get("alt") or "").strip(),
            })
        return images

    @staticmethod
    def _inline_image_context(body: str, marker: str, alt: str = "") -> str:
        position = body.find(marker)
        if position < 0:
            return f"[HTML 대체 텍스트] {alt}" if alt else ""
        before = re.sub(r"\s+", " ", body[max(0, position - 500):position]).strip()
        after_start = position + len(marker)
        after = re.sub(r"\s+", " ", body[after_start:after_start + 500]).strip()
        parts = []
        if before:
            parts.append(f"[앞 문맥] {before[-400:]}")
        if alt:
            parts.append(f"[HTML 대체 텍스트] {alt}")
        parts.append(f"[그림 위치] {marker}")
        if after:
            parts.append(f"[뒤 문맥] {after[:400]}")
        return "\n".join(parts)

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
                "posted_at": (
                    date_node.get_text(" ", strip=True)
                    if (date_node := row.select_one(".td-date"))
                    else None
                ),
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

    def detect_total_pages(self) -> int:
        """목록 HTML이 제공하는 실제 마지막 페이지를 읽는다."""
        first_url = (
            self.config.list_url_template.format(page=1)
            if self.config.list_url_template
            else self.config.list_url
        )
        if not first_url:
            return max(1, self.config.pages)
        soup = self._fetch_html(first_url)
        node = soup.select_one("._totPage")
        if node:
            try:
                return max(1, int(node.get_text(strip=True).replace(",", "")))
            except ValueError:
                pass
        return max(1, self.config.pages)

    def _page_numbers(self, scope: CrawlPageScope) -> range:
        start = max(1, scope.start_page)
        if scope.mode in {"all", "recent"}:
            end = self.detect_total_pages()
        elif scope.mode == "range":
            end = min(
                self.detect_total_pages(),
                max(start, scope.end_page or start),
            )
        else:
            end = max(start, scope.end_page or self.config.pages)
        return range(start, end + 1)

    @staticmethod
    def _record_is_recent(record: dict, cutoff: date) -> bool:
        raw = str(record.get("posted_at") or "").strip()
        raw = raw.replace(".", "-").replace("/", "-").rstrip("-")
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date() >= cutoff
        except ValueError:
            # 날짜를 읽지 못했다면 누락보다 확인을 선택한다.
            return True

    def _collect_page_batches(
        self,
        scope: CrawlPageScope,
        recent_cutoff: date,
    ) -> list[tuple[int, list[dict]]]:
        """상세 처리 전에 목록 URL을 먼저 수집한다.

        전체/범위 모드는 가벼운 목록 요청만 2개씩 병렬로 받는다.
        최근 모드는 게시일 경계에서 멈춰야 하므로 순차 확인한다.
        """
        pages = list(self._page_numbers(scope))
        batches: list[tuple[int, list[dict]]] = []
        if scope.mode == "recent":
            for page_num in pages:
                records = self._collect_post_records(None, page_num)
                batches.append((page_num, records))
                ordinary = [record for record in records if not record.get("is_pinned")]
                if ordinary and not any(
                    self._record_is_recent(record, recent_cutoff)
                    for record in ordinary
                ):
                    print("     ↳ 최근 기준일 이전 페이지에 도달해 목록 확인을 종료합니다.")
                    break
            return batches

        def collect(page_num: int) -> tuple[int, list[dict]]:
            return page_num, self._collect_post_records(None, page_num)

        with ThreadPoolExecutor(max_workers=2) as executor:
            for index, batch in enumerate(executor.map(collect, pages), 1):
                batches.append(batch)
                if index % 100 == 0:
                    print(f"     ↳ 목록 URL 확인 {index}/{len(pages)}페이지")
        return batches

    def crawling(
        self,
        should_skip: Callable[[str], bool] | None = None,
        *,
        scope: CrawlPageScope | None = None,
        select_records: Callable[[list[dict]], list[dict]] | None = None,
        on_detail_failure: Callable[[str, str], None] | None = None,
    ) -> Iterator[dict]:
        scope = scope or CrawlPageScope()
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
            recent_cutoff = date.today() - timedelta(days=max(0, scope.recent_days))
            page_batches = self._collect_page_batches(scope, recent_cutoff)
            selected_url_set: set[str] | None = None
            if select_records:
                all_records: dict[str, dict] = {}
                for _page_num, records in page_batches:
                    for record in records:
                        if (
                            scope.mode != "recent"
                            or record.get("is_pinned")
                            or self._record_is_recent(record, recent_cutoff)
                        ):
                            all_records.setdefault(record["url"], record)
                selected_url_set = {
                    record["url"]
                    for record in select_records(list(all_records.values()))
                }
                print(
                    f"     ↳ 전체 URL DB 대조: {len(all_records)}건 중 "
                    f"{len(selected_url_set)}건 상세 처리"
                )
            for page_num, post_records in page_batches:
                processing_records = post_records
                if scope.mode == "recent":
                    processing_records = [
                        record for record in post_records
                        if record.get("is_pinned")
                        or self._record_is_recent(record, recent_cutoff)
                    ]

                if self.config.dedupe_urls:
                    new_records = [
                        record for record in processing_records
                        if record["url"] not in seen_urls
                    ]
                    seen_urls.update(record["url"] for record in new_records)
                else:
                    new_records = processing_records

                discovered = len(new_records)
                self.last_run_stats["discovered"] += discovered
                print(
                    f"\n=== {page_num}페이지: 게시글 {len(post_records)}건, "
                    f"처리 대상 {discovered}건 ==="
                )

                known_count = 0
                if selected_url_set is not None:
                    selected_records = [
                        record for record in new_records
                        if record["url"] in selected_url_set
                    ]
                    known_count = sum(
                        1 for record in new_records
                        if record["url"] not in selected_url_set
                    )
                    new_records = selected_records
                    self.last_run_stats["known"] += known_count
                    print(
                        f"     ↳ DB URL 대조: {known_count}건 상세 생략, "
                        f"{len(new_records)}건 상세 처리"
                    )
                elif should_skip:
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
                            url = futures[future]
                            failure = None
                            try:
                                result = future.result()
                            except Exception as error:
                                result = None
                                failure = f"{type(error).__name__}: {error}"
                            if result is not None:
                                page_results.append(result)
                            elif on_detail_failure:
                                on_detail_failure(
                                    url,
                                    failure or "detail extraction returned no result",
                                )

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

        body_text = self._body_from_selector(
            soup,
            self.config.body_selector,
        )

        # body는 별도 저장
        body_content = body_text.strip() if body_text else ""

        # attachment text는 별도 저장
        attachment_contents: list[dict] = []
        attachment_names: list[str] = []

        assets: list[dict] = []
        order = 0
        body_source_with_markers = body_content

        for image in self._collect_inline_images(soup):
            marker = image["marker"]
            context = self._inline_image_context(body_source_with_markers, marker, image.get("alt", ""))
            print(f"  - 본문 이미지 처리: {image['url']}")
            txt, raw_bytes, mime, analysis = inline_image_to_text(
                image["url"], http_context, context, marker,
            )

            if raw_bytes is None:
                body_content = body_content.replace(marker, "", 1)
                continue

            suffix = {
                "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
                "image/bmp": ".bmp",
            }.get(mime, ".jpg")
            filename = f"body-image-{image['number']:03d}{suffix}"
            figure = {
                "number": image["number"],
                "label": f"본문 그림 {image['number']}",
                "marker": marker,
                "scope": "body",
                "context": context,
                "matchMethod": "html_dom_order",
                "matchConfidence": 1.0,
            }
            description_lines = []
            description = str(analysis.get("description") or "").strip()
            ocr_text = str(analysis.get("ocrText") or "").strip()
            if description:
                description_lines.append(f"[그림 설명] {description}")
            if ocr_text and ocr_text != description:
                description_lines.append(f"[그림 내 텍스트] {ocr_text}")
            if description_lines and analysis.get("contextMatch") != "unrelated":
                body_content = body_content.replace(
                    marker, marker + "\n" + "\n".join(description_lines), 1,
                )

            extracted_text = (
                f"{marker}\n{context}\n[그림 설명] {txt}"
                if txt else f"{marker}\n{context}"
            ).strip()
            assets.append({
                "kind": "inline_image",
                "filename": filename,
                "source_url": image["url"],
                "storage_path": self._save_image_asset(raw_bytes, mime),
                "mime_type": mime,
                "extracted_text": extracted_text,
                "extra": {
                    "parentAttachment": "__body__",
                    "figure": figure,
                    "analysis": analysis,
                    "width": analysis.get("width"),
                    "height": analysis.get("height"),
                },
                "order_idx": order,
            })
            order += 1

            if txt and analysis.get("contextMatch") != "unrelated":
                attachment_contents.append({
                    "name": f"__body__ · 본문 그림 {image['number']}",
                    "text": extracted_text,
                    "type": "body_figure",
                })

        # legacy full content도 실제 본문 그림 위치가 반영된 본문을 사용한다.
        content_parts = [body_content] if body_content else []

        include_xlsx = True  # 현재는 모든 첨부파일을 텍스트로 변환해서 포함하도록 설정되어 있습니다.
        review_reasons: list[str] = []
        extraction_quality: list[dict] = []
        # xlsx_relevant(title, body_text) >> 만약 제목이나 본문에 '공고', '모집', '채용' 같은 단어가 있으면, 첨부된 엑셀 파일도 텍스트로 변환해서 내용에 포함할지 여부 판단하고 싶으면 이 함수를 활용할 수 있습니다. 
       
        for att in self._collect_attachments(soup):
            print(f"  - 첨부 처리: {att['filename']}")

            txt, meta = attachment_to_text(
                {**att, "preview_url": None},
                http_context,
                include_xlsx=include_xlsx,
            )
            if meta.get("review_required"):
                review_reasons.append(
                    str(meta.get("review_reason") or "attachment_review_required")
                )
            if isinstance(meta.get("quality"), dict):
                extraction_quality.append(meta["quality"])

            attachment_names.append(att["filename"])

            if txt and not meta.get("review_required"):
                attachment_contents.append({
                    "name": att["filename"],
                    "text": txt,
                    "type": meta.get("kind", "attachment"),
                })
                # Do not append attachment OCR to legacy content_parts to avoid duplicate retrieval contamination.

            storage_path = meta.get("storage_path")

            if meta.get("raw_bytes") is not None and not storage_path:
                storage_path = self._save_attachment_asset(
                    meta["raw_bytes"], att["filename"],
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
            # Document structure/validation files and embedded binaries are
            # audit artifacts only. They are persisted for inspection, but
            # never added to attachment_contents, which is the embedding input.
            for derived in meta.get("derived_assets") or []:
                analysis = derived.get("analysis") or {}
                figure = derived.get("figure") if isinstance(derived.get("figure"), dict) else None
                search_text = str(analysis.get("searchText") or derived.get("extracted_text") or "").strip()
                extracted_text = search_text
                if figure and search_text:
                    extracted_text = (
                        f"[그림 {figure.get('number')}]\n"
                        f"{str(figure.get('context') or '').strip()}\n"
                        f"[그림 설명] {search_text}"
                    ).strip()
                assets.append({
                    **derived,
                    "source_url": att["download_url"],
                    "extracted_text": extracted_text,
                    "extra": {
                        "parentAttachment": att["filename"],
                        "binaryId": derived.get("binaryId"),
                        "sha256": derived.get("sha256"),
                        "width": derived.get("width"),
                        "height": derived.get("height"),
                        "figure": figure,
                        "analysis": analysis,
                    },
                    "order_idx": order,
                })
                order += 1

            if not meta.get("review_required"):
                for figure_content in meta.get("figure_contents") or []:
                    text = str(figure_content.get("text") or "").strip()
                    if not text:
                        continue
                    attachment_contents.append({
                        "name": (
                            f"{att['filename']} · 그림 {figure_content.get('number')}"
                        ),
                        "text": text,
                        "type": "attachment_figure",
                    })

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
            "review_required": bool(review_reasons),
            "review_reason": ";".join(review_reasons),
            "extraction_quality": extraction_quality,
        }
