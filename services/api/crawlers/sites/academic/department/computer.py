from pathlib import Path

from crawlers.methods.curriculum_page import CurriculumConfig, CurriculumCrawler


COMPUTER_ACADEMIC_CRAWLERS = {
    "cse_curriculum": CurriculumCrawler(CurriculumConfig(
        source_code="cse_curriculum",
        source_name="컴퓨터공학과 교과과정표",
        department="컴퓨터공학과",
        base_url="https://computer.kongju.ac.kr",
        pdf_url="https://computer.kongju.ac.kr/documentViewer/ZD1140/251/1261/fileDown.do",
        page_url="https://computer.kongju.ac.kr/ZD1140/11579/subview.do",
        cache_path=Path("data/cache/curriculum/computer/curriculum.pdf"),
        document_selector="#viewerDocSelector option",
        document_url_template=(
            "https://computer.kongju.ac.kr/documentViewer/"
            "ZD1140/251/{document_id}/fileDown.do"
        ),
        document_cache_dir=Path("data/cache/curriculum/computer"),
    )),
}
