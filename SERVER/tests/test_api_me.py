from fastapi.testclient import TestClient

from api.main import app


def _patch(monkeypatch, account=None, user=None, courses=None, tasks=None):
    import api.routers.me as me_mod

    monkeypatch.setattr(me_mod, "get_account", lambda u: account)
    monkeypatch.setattr(me_mod, "get_user", lambda sid: user)
    monkeypatch.setattr(me_mod, "get_lms_courses", lambda sid: courses or [])
    monkeypatch.setattr(me_mod, "get_lms_tasks", lambda sid: tasks or [])


def test_me_unlinked_returns_empty(monkeypatch):
    # 포털 미연결(student_id 링크 없음) → 빈 프로필
    _patch(monkeypatch, account={"student_id": None})
    with TestClient(app) as client:
        r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["student_id"] is None
    assert body["portal_linked"] is False
    assert body["lms_linked"] is False


def test_me_linked_profile(monkeypatch):
    _patch(
        monkeypatch,
        account={"student_id": "202202165"},
        user={
            "name": "이승원",
            "major": "컴퓨터공학과",
            "year": 3,
            "interests": ["인턴", "장학금"],
            "timetable": [{"day": "월"}],
            "grade_distribution": None,
        },
        courses=[{"course_id": 1, "course_name": "자료구조"}],
    )
    with TestClient(app) as client:
        r = client.get("/api/me")
    body = r.json()
    assert body["name"] == "이승원"
    assert body["major"] == "컴퓨터공학과"
    assert body["interests"] == ["인턴", "장학금"]
    assert body["portal_linked"] is True  # timetable 있음
    assert body["lms_linked"] is True  # course 있음


def test_me_timetable(monkeypatch):
    _patch(
        monkeypatch,
        account={"student_id": "202202165"},
        user={"timetable": [{"title": "자료구조", "day": "월"}]},
    )
    with TestClient(app) as client:
        r = client.get("/api/me/timetable")
    assert r.json()["timetable"] == [{"title": "자료구조", "day": "월"}]


def test_me_portal_grades(monkeypatch):
    _patch(
        monkeypatch,
        account={"student_id": "202202165"},
        user={
            "grade_distribution": {"grids": {}},
            "cumulative_grades": {"gpa": 4.0},
            "graduation_credits": {"전공": {}},
        },
    )
    with TestClient(app) as client:
        r = client.get("/api/me/portal")
    body = r.json()
    assert body["cumulative_grades"] == {"gpa": 4.0}
    assert body["graduation_credits"] == {"전공": {}}


def test_me_lms_tasks_iso_date(monkeypatch):
    import datetime

    _patch(
        monkeypatch,
        account={"student_id": "202202165"},
        tasks=[{
            "id": 1, "task_type": "assignment", "title": "과제1",
            "course_name": "자료구조", "due_date": datetime.date(2026, 6, 20),
            "progress": None, "url": None, "is_done": False,
        }],
    )
    with TestClient(app) as client:
        r = client.get("/api/me/lms/tasks")
    task = r.json()["tasks"][0]
    assert task["due_date"] == "2026-06-20"  # date → ISO 문자열
    assert task["title"] == "과제1"


def test_me_lms_courses(monkeypatch):
    _patch(
        monkeypatch,
        account={"student_id": "202202165"},
        courses=[{"course_id": 10, "course_name": "운영체제"}],
    )
    with TestClient(app) as client:
        r = client.get("/api/me/lms/courses")
    assert r.json()["courses"] == [{"course_id": 10, "course_name": "운영체제"}]


def test_me_unlinked_lms_empty(monkeypatch):
    _patch(monkeypatch, account=None)  # 계정 자체 없음
    with TestClient(app) as client:
        r = client.get("/api/me/lms/tasks")
    assert r.status_code == 200
    assert r.json()["tasks"] == []
