from crawlers.sites.academic.department.business import BUSINESS_ACADEMIC_CRAWLERS
from crawlers.sites.academic.department.computer import COMPUTER_ACADEMIC_CRAWLERS
from crawlers.sites.academic.department.software import SOFTWARE_ACADEMIC_CRAWLERS


DEPARTMENT_ACADEMIC_CRAWLERS = {
    **COMPUTER_ACADEMIC_CRAWLERS,
    **SOFTWARE_ACADEMIC_CRAWLERS,
    **BUSINESS_ACADEMIC_CRAWLERS,
}

__all__ = ["DEPARTMENT_ACADEMIC_CRAWLERS"]
