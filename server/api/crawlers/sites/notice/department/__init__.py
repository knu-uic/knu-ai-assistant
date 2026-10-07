from crawlers.sites.notice.department.business import BUSINESS_NOTICE_CRAWLERS
from crawlers.sites.notice.department.computer import COMPUTER_NOTICE_CRAWLERS
from crawlers.sites.notice.department.software import SOFTWARE_NOTICE_CRAWLERS


DEPARTMENT_NOTICE_CRAWLERS = {
    **COMPUTER_NOTICE_CRAWLERS,
    **SOFTWARE_NOTICE_CRAWLERS,
    **BUSINESS_NOTICE_CRAWLERS,
}

__all__ = ["DEPARTMENT_NOTICE_CRAWLERS"]
