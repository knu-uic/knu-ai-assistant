from crawlers.sites.academic.department import DEPARTMENT_ACADEMIC_CRAWLERS
from crawlers.sites.academic.scholarship import SCHOLARSHIP_CRAWLERS


ACADEMIC_CRAWLER_MAP = {
    **SCHOLARSHIP_CRAWLERS,
    **DEPARTMENT_ACADEMIC_CRAWLERS,
}

ACADEMIC_CRAWLERS = [
    ACADEMIC_CRAWLER_MAP["cse_curriculum"],
    ACADEMIC_CRAWLER_MAP["software_curriculum"],
    ACADEMIC_CRAWLER_MAP["business_curriculum"],
    ACADEMIC_CRAWLER_MAP["scholarship_info"],
]

__all__ = ["ACADEMIC_CRAWLERS", "ACADEMIC_CRAWLER_MAP"]
