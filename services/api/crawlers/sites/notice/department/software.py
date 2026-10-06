from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler


SOFTWARE_NOTICE_CRAWLERS = {
    "software_notice": BoardNoticeCrawler(BoardNoticeConfig(
        source_code="software_notice",
        source_name="소프트웨어공학과 학과공지",
        department="소프트웨어공학과",
        base_url="https://sw.kongju.ac.kr",
        list_url="https://sw.kongju.ac.kr/ZD1180/11654/subview.do",
        list_url_template="https://sw.kongju.ac.kr/bbs/ZD1180/1423/artclList.do?page={page}",
        pages=5,
        max_workers=1,
        row_selector=".board-table tbody tr",
        list_wait_selector=".board-table tbody tr",
        dedupe_urls=True,
    )),
}
