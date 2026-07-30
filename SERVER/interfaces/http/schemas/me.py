"""Current-user transport schemas."""

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
    favorite_courses: List[str] = []
    portal_linked: bool = False
    portal_syncing: bool = False
    sync_stage: Optional[str] = None
    lms_sync_error: Optional[str] = None
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


class FavoritesRequest(BaseModel):
    favorite_courses: List[str] = []


class TaskDoneRequest(BaseModel):
    is_done: bool


class RecItem(BaseModel):
    title: str
    url: str
    summary: Optional[str] = None
    category: Optional[str] = None
    d_label: Optional[str] = None
    days_left: Optional[int] = None
    matched_keywords: List[str] = []


class DeadlineItem(BaseModel):
    title: str
    url: str
    category: Optional[str] = None
    end_date: str
    d_label: Optional[str] = None
    days_left: int


class HomeResponse(BaseModel):
    recommended: List[RecItem] = []
    deadlines: List[DeadlineItem] = []
