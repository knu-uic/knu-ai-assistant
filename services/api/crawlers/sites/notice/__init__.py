from crawlers.sites.notice.department import DEPARTMENT_NOTICE_CRAWLERS
from crawlers.sites.notice.student_notice import STUDENT_NOTICE_CRAWLERS


NOTICE_CRAWLER_MAP = {
    **STUDENT_NOTICE_CRAWLERS,
    **DEPARTMENT_NOTICE_CRAWLERS,
}

NOTICE_CRAWLERS = [
    NOTICE_CRAWLER_MAP["main_notice"],
    NOTICE_CRAWLER_MAP["cse_notice"],
    NOTICE_CRAWLER_MAP["software_notice"],
    NOTICE_CRAWLER_MAP["business_notice"],
]

__all__ = ["NOTICE_CRAWLERS", "NOTICE_CRAWLER_MAP"]
