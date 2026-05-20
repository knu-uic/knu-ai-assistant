from crawlers.sites.kongju import KONGJU_CRAWLERS
from crawlers.sites.departments.computer import COMPUTER_CRAWLERS

DEPARTMENT_CRAWLERS = {
    **COMPUTER_CRAWLERS,
}

CRAWLERS = [
    KONGJU_CRAWLERS["main_notice"],
    DEPARTMENT_CRAWLERS["cse_notice"],
    KONGJU_CRAWLERS["scholarship_info"],
]

__all__ = ["CRAWLERS", "DEPARTMENT_CRAWLERS", "KONGJU_CRAWLERS"]
