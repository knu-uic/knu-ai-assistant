from crawlers.sites.kongju import KONGJU_CRAWLERS
from crawlers.sites.departments.business import BUSINESS_CRAWLERS
from crawlers.sites.departments.computer import COMPUTER_CRAWLERS

DEPARTMENT_CRAWLERS = {
    **BUSINESS_CRAWLERS,
    **COMPUTER_CRAWLERS,
}

CRAWLERS = [
    KONGJU_CRAWLERS["main_notice"],
    DEPARTMENT_CRAWLERS["cse_curriculum"],
    DEPARTMENT_CRAWLERS["cse_notice"],
    DEPARTMENT_CRAWLERS["business_curriculum"],
    DEPARTMENT_CRAWLERS["business_notice"],
    KONGJU_CRAWLERS["scholarship_info"],
]

__all__ = ["CRAWLERS", "DEPARTMENT_CRAWLERS", "KONGJU_CRAWLERS"]
