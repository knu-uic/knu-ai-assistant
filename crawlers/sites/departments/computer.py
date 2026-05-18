from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler


COMPUTER_CRAWLERS = {
    "cse_notice": BoardNoticeCrawler(BoardNoticeConfig(
        source_code="cse_notice",
        source_name="컴퓨터공학과 학과공지",
        department="컴퓨터공학과",
        base_url="https://computer.kongju.ac.kr",
        list_url_template="https://computer.kongju.ac.kr/bbs/ZD1140/1410/artclList.do?page={page}",
        pages=5,
        row_selector=".board-table tbody tr",
        list_wait_selector=".board-table tbody tr",
        dedupe_urls=True,
    )),
}
