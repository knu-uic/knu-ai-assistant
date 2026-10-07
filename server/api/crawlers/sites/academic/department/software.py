from pathlib import Path

from crawlers.methods.curriculum_page import CurriculumConfig, CurriculumCrawler


SOFTWARE_ACADEMIC_CRAWLERS = {
    "software_curriculum": CurriculumCrawler(CurriculumConfig(
        source_code="software_curriculum",
        source_name="소프트웨어공학과 교과과정표",
        department="소프트웨어공학과",
        base_url="https://sw.kongju.ac.kr",
        pdf_url="https://sw.kongju.ac.kr/documentViewer/ZD1180/257/1258/fileDown.do",
        page_url="https://sw.kongju.ac.kr/ZD1180/11630/subview.do",
        cache_path=Path("data/cache/curriculum/software/curriculum.pdf"),
        document_selector="#viewerDocSelector option",
        document_url_template=(
            "https://sw.kongju.ac.kr/documentViewer/"
            "ZD1180/257/{document_id}/fileDown.do"
        ),
        document_cache_dir=Path("data/cache/curriculum/software"),
    )),
}
