from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import requests

from crawlers.methods.board_notice import (
    BoardNoticeConfig,
    BoardNoticeCrawler,
    _RequestsDownloadContext,
)
from extractors.attachments import _download


class _Response:
    def __init__(self, *, text="ok", content=None, status_code=200):
        self.text = text
        self.content = content if content is not None else text.encode()
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _BrowserContext:
    def __init__(self):
        self.run_count = 0
        self.closed = False

    def run(self, callback):
        self.run_count += 1
        raise AssertionError("ordinary HTML notices must not launch Chromium")

    def close(self):
        self.closed = True


class _ExecutingBrowserContext(_BrowserContext):
    def __init__(self):
        super().__init__()
        self.context = object()

    def run(self, callback):
        self.run_count += 1
        return callback(self.context)


def _config(**changes):
    base = BoardNoticeConfig(
        source_code="test_notice",
        source_name="테스트 공지",
        department="공통",
        base_url="https://example.test",
        list_url_template="https://example.test/list?page={page}",
        pages=1,
    )
    return replace(base, **changes)


def test_detail_uses_fetched_html_without_opening_chromium(monkeypatch):
    crawler = BoardNoticeCrawler(_config())
    browser = _BrowserContext()
    crawler._browser_context_factory = lambda: browser
    monkeypatch.setattr(
        crawler,
        "_fetch_html_text",
        lambda url: """
            <h1 class="view-title">HTTP 한 번으로 읽은 공지</h1>
            <div class="write"><dd>2026.09.02</dd></div>
            <div class="view-con">본문입니다.</div>
        """,
    )

    item = crawler.crawl_detail("https://example.test/notice/1")

    assert item["title"] == "HTTP 한 번으로 읽은 공지"
    assert item["body_content"] == "본문입니다."
    assert browser.run_count == 0
    assert browser.closed is True


def test_failed_hwp_originals_fall_back_to_one_reused_browser_context(monkeypatch):
    import crawlers.methods.board_notice as board_notice

    crawler = BoardNoticeCrawler(_config())
    browser = _ExecutingBrowserContext()
    crawler._browser_context_factory = lambda: browser
    monkeypatch.setattr(
        crawler,
        "_fetch_html_text",
        lambda url: """
            <h1 class="view-title">HWP 첨부 공지</h1>
            <div class="write"><dd>2026.09.02</dd></div>
            <div class="view-con">본문입니다.</div>
            <ul class="view-file">
              <li><a href="/1/download.do">첫째.hwp</a><a href="/1/synapView.do">미리보기</a></li>
              <li><a href="/2/download.do">둘째.hwp</a><a href="/2/synapView.do">미리보기</a></li>
            </ul>
        """,
    )
    seen_contexts = []
    monkeypatch.setattr(
        board_notice,
        "hwp_via_preview",
        lambda url, context: seen_contexts.append(context) or f"{url} 본문",
    )
    monkeypatch.setattr(
        board_notice,
        "attachment_to_text",
        lambda att, context, include_xlsx=False: (
            f"[첨부: {att['filename']}]\n(처리 실패: test)",
            {
                "kind": "attachment_hwp",
                "filename": att["filename"],
                "source_url": att["download_url"],
                "mime_type": "application/x-hwp",
                "raw_bytes": None,
                "extracted_text": "(처리 실패: test)",
            },
        ),
    )

    item = crawler.crawl_detail("https://example.test/notice/hwp")

    assert item["attachment_names"] == ["첫째.hwp", "둘째.hwp"]
    assert browser.run_count == 2
    assert seen_contexts == [browser.context, browser.context]
    assert browser.closed is True


def test_successful_hwp_original_does_not_open_browser(monkeypatch):
    import crawlers.methods.board_notice as board_notice

    crawler = BoardNoticeCrawler(_config())
    browser = _BrowserContext()
    crawler._browser_context_factory = lambda: browser
    monkeypatch.setattr(
        crawler,
        "_fetch_html_text",
        lambda url: """
            <h1 class="view-title">HWP 첨부 공지</h1>
            <div class="write"><dd>2026.09.02</dd></div>
            <div class="view-con">본문입니다.</div>
            <ul class="view-file">
              <li><a href="/1/download.do">요람.hwp</a><a href="/1/synapView.do">미리보기</a></li>
            </ul>
        """,
    )
    monkeypatch.setattr(
        board_notice,
        "attachment_to_text",
        lambda att, context, include_xlsx=False: (
            "[첨부: 요람.hwp]\n원본에서 추출한 전체 본문",
            {
                "kind": "attachment_hwp",
                "filename": "요람.hwp",
                "source_url": att["download_url"],
                "mime_type": "application/x-hwp",
                "raw_bytes": None,
                "extracted_text": "원본에서 추출한 전체 본문",
            },
        ),
    )

    item = crawler.crawl_detail("https://example.test/notice/hwp")

    assert item["attachment_contents"][0]["type"] == "attachment_hwp"
    assert browser.run_count == 0
    assert browser.closed is True


def test_http_retry_uses_exponential_backoff_before_success():
    crawler = BoardNoticeCrawler(_config())
    session = _Session(
        [
            requests.ReadTimeout("first"),
            requests.ConnectTimeout("second"),
            _Response(text="recovered"),
        ]
    )
    crawler._session_local.value = session
    delays = []
    crawler._sleep = delays.append

    response = crawler._fetch_response(
        "https://example.test/notice/1",
        timeout_seconds=75,
        attempts=3,
        backoff_seconds=3,
    )

    assert response.text == "recovered"
    assert [timeout for _, timeout in session.calls] == [75, 75, 75]
    assert delays == [3, 9]


def test_large_attachment_download_retries_and_returns_complete_bytes():
    crawler = BoardNoticeCrawler(_config())
    expected = b"x" * (20 * 1024 * 1024 + 1)
    session = _Session(
        [
            requests.ReadTimeout("large file stalled"),
            _Response(content=expected),
        ]
    )
    crawler._session_local.value = session
    crawler._sleep = lambda seconds: None

    result = _download(
        "https://example.test/large.pdf",
        _RequestsDownloadContext(crawler),
    )

    assert result == expected
    assert len(session.calls) == 2
    assert all(timeout == 180 for _, timeout in session.calls)


def test_real_http_timeout_then_retry_recovers_twenty_megabyte_response():
    expected = b"z" * (20 * 1024 * 1024 + 1)

    class Handler(BaseHTTPRequestHandler):
        attempts = 0

        def do_GET(self):
            type(self).attempts += 1
            if type(self).attempts == 1:
                time.sleep(1.2)
            self.send_response(200)
            self.send_header("Content-Length", str(len(expected)))
            self.end_headers()
            try:
                self.wfile.write(expected)
            except BrokenPipeError:
                pass

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    crawler = BoardNoticeCrawler(_config())
    crawler._sleep = lambda seconds: None
    try:
        response = crawler._fetch_response(
            f"http://127.0.0.1:{server.server_port}/large.pdf",
            timeout_seconds=1,
            attempts=3,
            backoff_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert Handler.attempts == 2
    assert response.content == expected


def test_page_results_wait_for_minimum_success_evidence(monkeypatch):
    crawler = BoardNoticeCrawler(_config(min_success_ratio=0.5, min_success_count=3))
    browser = _BrowserContext()
    crawler._browser_context_factory = lambda: browser
    records = [
        {"url": f"https://example.test/notice/{index}", "is_pinned": False}
        for index in range(4)
    ]
    monkeypatch.setattr(crawler, "_collect_post_records", lambda page, number: records)
    monkeypatch.setattr(
        crawler,
        "_crawl_post_parallel",
        lambda browser_context, url, idx, total, is_pinned=False: (
            {"url": url} if idx == 1 else None
        ),
    )

    assert list(crawler.crawling()) == []
    assert crawler.last_run_stats == {
        "discovered": 4,
        "known": 0,
        "succeeded": 1,
        "failed": 3,
        "accepted_pages": 0,
        "rejected_pages": 1,
    }


def test_known_and_new_successes_can_meet_page_threshold(monkeypatch):
    crawler = BoardNoticeCrawler(_config(min_success_ratio=0.5, min_success_count=3))
    crawler._browser_context_factory = _BrowserContext
    records = [
        {"url": f"https://example.test/notice/{index}", "is_pinned": False}
        for index in range(4)
    ]
    monkeypatch.setattr(crawler, "_collect_post_records", lambda page, number: records)
    monkeypatch.setattr(
        crawler,
        "_crawl_post_parallel",
        lambda browser_context, url, idx, total, is_pinned=False: {"url": url},
    )

    items = list(
        crawler.crawling(
            should_skip=lambda url: url.endswith("/0") or url.endswith("/1")
        )
    )

    assert len(items) == 2
    assert crawler.last_run_stats["known"] == 2
    assert crawler.last_run_stats["succeeded"] == 2
    assert crawler.last_run_stats["accepted_pages"] == 1


def test_kongju_common_board_limits_parallelism_to_two():
    from crawlers.sites.kongju import KONGJU_CRAWLERS

    assert KONGJU_CRAWLERS["main_notice"].config.max_workers == 2
