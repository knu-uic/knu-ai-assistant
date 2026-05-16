from pathlib import Path

from crawlers.methods.board_notice import BoardNoticeConfig, BoardNoticeCrawler
from crawlers.methods.curriculum import CurriculumConfig, CurriculumCrawler


COMPUTER_CRAWLERS = {
    "cse_curriculum": CurriculumCrawler(CurriculumConfig(
        source_code="cse_curriculum",
        source_name="컴퓨터공학과 교과과정표",
        department="컴퓨터공학과",
        base_url="https://computer.kongju.ac.kr",
        pdf_url="https://computer.kongju.ac.kr/documentViewer/ZD1140/251/1261/fileDown.do",
        page_url="https://computer.kongju.ac.kr/ZD1140/11579/subview.do",
        cache_path=Path("crawl_result/cse_curriculum/curriculum.pdf"),
    )),
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
