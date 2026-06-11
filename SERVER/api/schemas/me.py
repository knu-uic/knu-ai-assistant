from typing import List, Optional

from pydantic import BaseModel


class InterestsRequest(BaseModel):
    interests: List[str] = []


class MeProfile(BaseModel):
    student_id: Optional[str] = None
    name: Optional[str] = None
    major: Optional[str] = None
    year: Optional[int] = None
    interests: List[str] = []
    portal_linked: bool = False
    lms_linked: bool = False


class TimetableResponse(BaseModel):
    # 포털 시간표 원본 JSON 구조를 그대로 전달 (없으면 null).
    timetable: Optional[list] = None


class PortalDataResponse(BaseModel):
    grade_distribution: Optional[dict] = None
    cumulative_grades: Optional[dict] = None
    graduation_credits: Optional[dict] = None


class LmsTask(BaseModel):
    id: int
    task_type: str
    title: str
    course_name: Optional[str] = None
    due_date: Optional[str] = None
    progress: Optional[int] = None
    url: Optional[str] = None
    is_done: bool = False


class LmsTasksResponse(BaseModel):
    tasks: List[LmsTask] = []


class LmsCourse(BaseModel):
    course_id: int
    course_name: str


class LmsCoursesResponse(BaseModel):
    courses: List[LmsCourse] = []
