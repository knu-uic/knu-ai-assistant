from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler
from crawlers.methods.static_page import StaticPageConfig, StaticPageCrawler


KONGJU_CRAWLERS = {
    "main_notice": BoardNoticeCrawler(BoardNoticeConfig(
        source_code="main_notice",
        source_name="공주대학교 일반 공지",
        department=None,
        base_url="https://www.kongju.ac.kr",
        list_url="https://www.kongju.ac.kr/KNU/16909/subview.do",
        page_title_template="{page}페이지",
        pages=5,
        row_selector="tr:has(.td-subject a)",
        row_selector_after_first="tr:not(.notice):has(.td-subject a)",
    )),
    "scholarship_info": StaticPageCrawler(StaticPageConfig(
        source_code="scholarship_info",
        source_name="공주대학교 장학안내",
        department=None,
        kind="academic",
        base_url="https://www.kongju.ac.kr",
        page_url="https://www.kongju.ac.kr/KNU/16842/subview.do",
        wait_selector="article",
        title_selector="h2",
        content_selector="article",
    )),
}
