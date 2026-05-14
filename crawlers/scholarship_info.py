"""공주대학교 장학안내 페이지 크롤러.

게시판이 아닌 단일 정적 정보 페이지(/KNU/16842/subview.do).
페이지네이션·첨부·본문 이미지 없음 → 표 포함 본문 텍스트만 단일 문서로 적재.
"""

from typing import Callable, List, Optional

from playwright.sync_api import sync_playwright

SOURCE_CODE = "scholarship_info"
SOURCE_NAME = "공주대학교 장학안내"
DEPARTMENT: str | None = None
KIND = "academic"
BASE_URL = "https://www.kongju.ac.kr"

PAGE_URL = "https://www.kongju.ac.kr/KNU/16842/subview.do"


def crawling(should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """should_skip(url): True면 진입 자체를 스킵. 단일 페이지이므로 한 번만 검사."""
    if should_skip and should_skip(PAGE_URL):
        print(f"[{SOURCE_CODE}] DB에 이미 적재됨 — 스킵")
        return []

    print(f"\n=== {SOURCE_NAME} 수집: {PAGE_URL} ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(PAGE_URL, wait_until="networkidle")
        page.wait_for_selector("article")

        try:
            title = page.locator("h2").first.inner_text().strip()
        except Exception:
            title = SOURCE_NAME

        try:
            content = page.locator("article").first.inner_text().strip()
        except Exception:
            content = ""

        browser.close()

    if not content:
        print(f"[{SOURCE_CODE}] 본문 추출 실패")
        return []

    print(f"제목: {title}")
    print(content[:300] + ("..." if len(content) > 300 else ""))

    return [{
        "title": title,
        "date": "",
        "content": content,
        "url": PAGE_URL,
        "assets": [],
    }]
