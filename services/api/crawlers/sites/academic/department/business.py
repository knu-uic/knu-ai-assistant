from pathlib import Path

from crawlers.methods.curriculum_page import CurriculumConfig, CurriculumCrawler


BUSINESS_ACADEMIC_CRAWLERS = {
    "business_curriculum": CurriculumCrawler(CurriculumConfig(
        source_code="business_curriculum",
        source_name="경영학과 교과과정표",
        department="경영학과",
        base_url="https://business.kongju.ac.kr",
        pdf_url="https://business.kongju.ac.kr/documentViewer/ZB0431/145/138/fileDown.do",
        page_url="https://business.kongju.ac.kr/ZB0431/145/subview.do",
        cache_path=Path("data/cache/curriculum/business/curriculum.hwp"),
        verify_ssl=False,
    )),
}
