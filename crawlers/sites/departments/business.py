from pathlib import Path

from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler
from crawlers.methods.direct_file import DirectFileConfig, DirectFileCrawler


BUSINESS_CRAWLERS = {
    "business_curriculum": DirectFileCrawler(DirectFileConfig(
        source_code="business_curriculum",
        source_name="경영학과 교과과정표",
        department="경영학과",
        base_url="https://business.kongju.ac.kr",
        file_url="https://business.kongju.ac.kr/documentViewer/ZB0431/145/138/fileDown.do",
        page_url="https://business.kongju.ac.kr/ZB0431/145/subview.do",
        cache_path=Path("crawl_result/business_curriculum/curriculum.hwp"),
        category="수강",
        keywords=["교과과정", "전공", "학점"],
        filename="경영학과 교과과정표.hwp",
        mime_type="application/x-hwp",
        verify_ssl=False,
    )),
    "business_notice": BoardNoticeCrawler(BoardNoticeConfig(
        source_code="business_notice",
        source_name="경영학과 학과공지",
        department="경영학과",
        base_url="https://business.kongju.ac.kr",
        list_url="https://business.kongju.ac.kr/ZB0431/2177/subview.do",
        page_title_template="{page}페이지",
        pages=5,
        row_selector=".board-table tbody tr:has(.td-subject a)",
        row_selector_after_first=".board-table tbody tr:not(.notice):has(.td-subject a)",
        list_wait_selector=".board-table tbody tr",
        dedupe_urls=True,
        wait_until="domcontentloaded",
    )),
}
