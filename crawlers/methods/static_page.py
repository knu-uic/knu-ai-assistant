from dataclasses import dataclass
from typing import Callable, List, Optional

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class StaticPageConfig:
    source_code: str
    source_name: str
    department: str | None
    kind: str
    base_url: str
    page_url: str
    wait_selector: str
    title_selector: str
    content_selector: str


class StaticPageCrawler:
    def __init__(self, config: StaticPageConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.KIND = config.kind
        self.BASE_URL = config.base_url

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        if should_skip and should_skip(self.config.page_url):
            print(f"[{self.SOURCE_CODE}] DB에 이미 적재됨 - 스킵")
            return []

        print(f"\n=== {self.SOURCE_NAME} 수집: {self.config.page_url} ===")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(self.config.page_url, wait_until="networkidle")
            page.wait_for_selector(self.config.wait_selector)

            try:
                title = page.locator(self.config.title_selector).first.inner_text().strip()
            except Exception:
                title = self.SOURCE_NAME

            try:
                content = page.locator(self.config.content_selector).first.inner_text().strip()
            except Exception:
                content = ""

            browser.close()

        if not content:
            print(f"[{self.SOURCE_CODE}] 본문 추출 실패")
            return []

        print(f"제목: {title}")
        print(content[:300] + ("..." if len(content) > 300 else ""))

        return [{
            "title": title,
            "date": "",
            "content": content,
            "url": self.config.page_url,
            "assets": [],
        }]
