from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler


STUDENT_NOTICE_CRAWLERS = {
    "main_notice": BoardNoticeCrawler(BoardNoticeConfig(
        source_code="main_notice",
        source_name="공주대학교 학생 공지",
        department="공통",
        base_url="https://www.kongju.ac.kr",
        list_url="https://www.kongju.ac.kr/KNU/16909/subview.do",
        list_url_template="https://www.kongju.ac.kr/KNU/16909/subview.do?page={page}",
        page_title_template="{page}페이지",
        pages=10,
        max_workers=2,
        row_selector="tr:has(.td-subject a)",
        row_selector_after_first="tr:not(.notice):has(.td-subject a)",
    )),
}
