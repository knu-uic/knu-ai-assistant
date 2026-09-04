from dataclasses import replace
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import requests
from bs4 import BeautifulSoup

from crawlers.methods.board_notice import (
    BoardNoticeConfig,
    BoardNoticeCrawler,
    CrawlPageScope,
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


def test_body_preserves_blocks_joins_inline_spans_and_keeps_links(monkeypatch):
    crawler = BoardNoticeCrawler(_config())
    browser = _BrowserContext()
    crawler._browser_context_factory = lambda: browser
    monkeypatch.setattr(
        crawler,
        "_fetch_html_text",
        lambda url: """
            <h1 class="view-title">줄바꿈 테스트</h1>
            <div class="write"><dd>2026.09.02</dd></div>
            <div class="view-con">
              <p><span>2026</span><span>학년도</span> <b>2학기</b> 안내</p>
              <p>신청은 <a href="/apply">신청 페이지</a>에서 진행</p>
              <p><a href="https://wrong.test">staff@example.test</a></p>
              <p><a href="https://wrong.test">----------------</a></p>
              <div>첫째 줄<br/>둘째 줄</div>
            </div>
        """,
    )

    item = crawler.crawl_detail("https://example.test/notice/links")

    assert "2026학년도 2학기 안내" in item["body_content"]
    assert "2026\n학년도" not in item["body_content"]
    assert "[신청 페이지](https://example.test/apply)" in item["body_content"]
    assert "[staff@example.test]" not in item["body_content"]
    assert "[----------------]" not in item["body_content"]
    assert "첫째 줄\n둘째 줄" in item["body_content"]


def test_inline_body_image_keeps_dom_position_context_and_figure_contract(monkeypatch):
    import crawlers.methods.board_notice as board_notice

    crawler = BoardNoticeCrawler(_config())
    browser = _BrowserContext()
    crawler._browser_context_factory = lambda: browser
    crawler._save_image_asset = lambda raw, mime: "/tmp/body-image.png"
    monkeypatch.setattr(
        crawler,
        "_fetch_html_text",
        lambda url: """
            <h1 class="view-title">본문 그림 안내</h1>
            <div class="write"><dd>2026.09.03</dd></div>
            <div class="view-con">
              <p>포털에서 수강 메뉴를 선택합니다.</p>
              <img src="/images/guide.png" alt="수강 메뉴 화면"/>
              <p>선택 후 저장 버튼을 누릅니다.</p>
              <img src="/images/guide.png" alt="중복 이미지"/>
            </div>
        """,
    )
    monkeypatch.setattr(
        board_notice,
        "inline_image_to_text",
        lambda url, context, document_context="", filename="": (
            "수강 메뉴와 저장 버튼이 표시된 포털 화면",
            b"fake-png",
            "image/png",
            {
                "kind": "scanned_text",
                "ocrText": "수강 메뉴 저장",
                "description": "포털 수강 메뉴 선택 화면",
                "contextMatch": "supports",
                "confidence": 0.98,
                "width": 800,
                "height": 600,
            },
        ),
    )

    item = crawler.crawl_detail("https://example.test/notice/body-image")

    before = item["body_content"].index("포털에서 수강 메뉴")
    marker = item["body_content"].index("[본문 그림 1]")
    after = item["body_content"].index("선택 후 저장 버튼")
    assert before < marker < after
    assert "[그림 설명] 포털 수강 메뉴 선택 화면" in item["body_content"]
    assert item["body_content"].count("[본문 그림 1]") == 1
    assert "[본문 그림 2]" not in item["body_content"]
    assert len(item["assets"]) == 1
    assert item["assets"][0]["kind"] == "inline_image"
    assert item["assets"][0]["extra"]["figure"]["marker"] == "[본문 그림 1]"
    assert "[앞 문맥] 포털에서 수강 메뉴를 선택합니다." in item["assets"][0]["extra"]["figure"]["context"]
    assert item["attachment_contents"][0]["type"] == "body_figure"
    assert item["attachment_contents"][0]["name"].startswith("__body__")


def test_attachment_fallback_finds_download_links_without_list_selector():
    crawler = BoardNoticeCrawler(_config(attachment_selector=".missing li"))
    soup = BeautifulSoup("""
      <div class="view-file">
        <div><a href="/bbs/X/1/download.do">안내.xlsx</a></div>
        <div><a href="/bbs/X/2/download.do">안내.hwp</a></div>
      </div>
    """, "html.parser")

    attachments = crawler._collect_attachments(soup)

    assert [item["filename"] for item in attachments] == ["안내.xlsx", "안내.hwp"]
    assert attachments[0]["download_url"] == "https://example.test/bbs/X/1/download.do"


def test_failed_hwp_originals_are_quarantined_without_opening_preview(monkeypatch):
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
                "review_required": True,
                "review_reason": "structured_extraction_failed:RuntimeError",
            },
        ),
    )

    item = crawler.crawl_detail("https://example.test/notice/hwp")

    assert item["attachment_names"] == ["첫째.hwp", "둘째.hwp"]
    assert browser.run_count == 0
    assert item["review_required"] is True
    assert "structured_extraction_failed" in item["review_reason"]
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
                "derived_assets": [
                    {
                        "kind": "attachment_hwp_structure",
                        "filename": "document.json",
                        "storage_path": "/tmp/document.json",
                        "mime_type": "application/json",
                        "extracted_text": "내부 품질 데이터",
                    },
                    {
                        "kind": "attachment_hwp_image",
                        "filename": "BIN0001.bmp",
                        "storage_path": "/tmp/BIN0001.bmp",
                        "mime_type": "image/bmp",
                        "extracted_text": "내부 이미지 설명",
                        "figure": {"number": 1, "label": "그림 1", "context": "검증된 문맥"},
                        "analysis": {"description": "내부 이미지 설명", "searchText": "내부 이미지 설명"},
                    },
                ],
                "figure_contents": [
                    {"number": 1, "filename": "BIN0001.bmp", "text": "[그림 1]\n검증된 문맥과 설명"},
                ],
            },
        ),
    )

    item = crawler.crawl_detail("https://example.test/notice/hwp")

    assert item["attachment_contents"][0]["type"] == "attachment_hwp"
    assert [entry["name"] for entry in item["attachment_contents"]] == [
        "요람.hwp", "요람.hwp · 그림 1",
    ]
    assert item["attachment_contents"][1]["type"] == "attachment_figure"
    assert [asset["filename"] for asset in item["assets"]] == [
        "요람.hwp", "document.json", "BIN0001.bmp",
    ]
    assert item["assets"][2]["extra"]["parentAttachment"] == "요람.hwp"
    assert item["assets"][2]["extra"]["figure"]["number"] == 1
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


def test_kongju_common_board_uses_student_notice_display_name():
    from crawlers.sites.kongju import KONGJU_CRAWLERS

    assert KONGJU_CRAWLERS["main_notice"].SOURCE_NAME == "공주대학교 학생 공지"


def test_full_scope_continues_after_page_whose_urls_are_all_known(monkeypatch):
    crawler = BoardNoticeCrawler(_config(pages=30, dedupe_urls=True))
    crawler._browser_context_factory = _BrowserContext
    visited = []
    partial_urls = {
        f"https://example.test/notice/{page}"
        for page in range(3, 21)
    }

    def records(_page, page_number):
        visited.append(page_number)
        return [{
            "url": f"https://example.test/notice/{page_number}",
            "is_pinned": False,
            "posted_at": "2020-01-01",
        }]

    monkeypatch.setattr(crawler, "detect_total_pages", lambda: 30)
    monkeypatch.setattr(crawler, "_collect_post_records", records)
    monkeypatch.setattr(
        crawler,
        "_crawl_post_parallel",
        lambda _browser, url, *_args, **_kwargs: {"url": url},
    )

    items = list(crawler.crawling(
        scope=CrawlPageScope(mode="all"),
        select_records=lambda rows: [
            row for row in rows if row["url"] not in partial_urls
        ],
    ))

    assert visited == list(range(1, 31))
    assert len(items) == 12
    assert crawler.last_run_stats["known"] == 18


def test_range_scope_visits_only_requested_pages(monkeypatch):
    crawler = BoardNoticeCrawler(_config(pages=100))
    crawler._browser_context_factory = _BrowserContext
    visited = []
    monkeypatch.setattr(crawler, "detect_total_pages", lambda: 100)
    monkeypatch.setattr(
        crawler,
        "_collect_post_records",
        lambda _page, page_number: visited.append(page_number) or [],
    )

    assert list(crawler.crawling(
        scope=CrawlPageScope(mode="range", start_page=3, end_page=20),
    )) == []
    assert visited == list(range(3, 21))


def test_recent_scope_stops_at_first_page_older_than_cutoff(monkeypatch):
    crawler = BoardNoticeCrawler(_config(pages=100))
    crawler._browser_context_factory = _BrowserContext
    visited = []
    today = date.today().isoformat()

    def records(_page, page_number):
        visited.append(page_number)
        return [{
            "url": f"https://example.test/notice/{page_number}",
            "is_pinned": False,
            "posted_at": today if page_number < 3 else "2020-01-01",
        }]

    monkeypatch.setattr(crawler, "detect_total_pages", lambda: 100)
    monkeypatch.setattr(crawler, "_collect_post_records", records)
    monkeypatch.setattr(
        crawler,
        "_crawl_post_parallel",
        lambda _browser, url, *_args, **_kwargs: {"url": url},
    )

    items = list(crawler.crawling(
        scope=CrawlPageScope(mode="recent", recent_days=7),
    ))

    assert visited == [1, 2, 3]
    assert [item["url"] for item in items] == [
        "https://example.test/notice/1",
        "https://example.test/notice/2",
    ]
