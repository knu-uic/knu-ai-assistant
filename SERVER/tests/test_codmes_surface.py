import datetime

import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_codmes_surface_returns_declarative_collection(monkeypatch):
    fake_rows = [(
        "https://x/notice-1", "장학금 신청 안내", "신청 본문",
        datetime.date(2026, 7, 28), None, datetime.date(2026, 8, 5),
        "장학", ["재학생"], ["장학금", "신청"],
        "KNU", "학생지원과", "notice", None, "신청 요약",
    )]
    import api.routers.codmes_surface as surface

    monkeypatch.setattr(surface, "get_documents", lambda **kwargs: fake_rows)
    with TestClient(app) as client:
        response = client.get("/api/codmes/surface")

    assert response.status_code == 200
    document = response.json()
    assert document["schemaVersion"] == 1
    assert document["presentation"] == "collection"
    assert document["search"]["fields"] == ["title", "body", "subtitle", "tags"]
    assert document["filters"][0]["id"] == "category"
    assert document["items"][0]["title"] == "장학금 신청 안내"
    assert document["items"][0]["filterValues"]["category"] == "장학"
    assert document["items"][0]["action"] == {
        "type": "openURL",
        "url": "https://x/notice-1",
    }


@pytest.mark.real_auth
def test_private_codmes_surface_requires_login():
    with TestClient(app) as client:
        response = client.get("/api/codmes/surface/lms")

    assert response.status_code == 401


def test_lms_codmes_surface_uses_logged_in_student(monkeypatch):
    from api.deps import create_access_token
    import api.routers.codmes_surface as surface

    monkeypatch.setattr(
        surface,
        "get_account",
        lambda username: {"username": username, "student_id": "20260001"},
    )
    monkeypatch.setattr(
        surface,
        "get_lms_tasks",
        lambda student_id, include_done: [{
            "id": 7,
            "task_type": "assignment",
            "title": "과제 제출",
            "course_name": "테스트 강의",
            "due_date": "2026-08-01",
            "url": "https://example.edu/task/7",
            "is_done": False,
        }],
    )
    token = create_access_token("student1")

    with TestClient(app) as client:
        response = client.get(
            "/api/codmes/surface/lms",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    document = response.json()
    assert document["title"] == "LMS"
    assert document["items"][0]["title"] == "과제 제출"


@pytest.mark.real_auth
def test_portal_principal_uses_student_id_without_pick_account(monkeypatch):
    from api.deps import create_portal_access_token
    import api.routers.codmes_surface as surface

    monkeypatch.setattr(
        surface,
        "get_user",
        lambda student_id: {
            "student_id": student_id,
            "name": "테스트 학생",
            "major": "컴퓨터공학과",
            "year": 2,
            "timetable": [{
                "rows": [
                    ["교시", "월요일", "화요일"],
                    ["1교시 (09:00~09:50)", "자료구조", ""],
                ],
            }],
            "graduation_credits": {
                "전공": {"계": {"기준": "60", "취득": "48"}},
            },
            "grade_distribution": {
                "summary": [["평점평균", "4.1"]],
                "grids": {},
            },
            "cumulative_grades": {
                "grids": {
                    "G1": {
                        "title": "과목별 성적",
                        "columns": ["년도", "과목명", "등급"],
                        "rows": [["2026", "자료구조", "A+"]],
                    },
                },
            },
        },
    )
    token = create_portal_access_token("20260001")

    with TestClient(app) as client:
        response = client.get(
            "/api/codmes/surface/portal",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    document = response.json()
    assert document["presentation"] == "dashboard"
    assert document["sections"][0]["fields"][0]["value"] == "20260001"
    assert any(section["id"] == "timetable" for section in document["sections"])
    assert any(section["id"] == "graduation" for section in document["sections"])
    assert any(
        section["id"].startswith("cumulative-grades")
        for section in document["sections"]
    )
