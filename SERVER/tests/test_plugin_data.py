from fastapi.testclient import TestClient

from api.main import app


def test_portal_plugin_data_contains_domain_data_without_ui_schema(monkeypatch):
    from api.deps import create_portal_access_token
    import api.routers.plugin_data as plugin_data

    monkeypatch.setattr(
        plugin_data,
        "portal_student_id",
        lambda principal: "20260001",
    )
    monkeypatch.setattr(
        plugin_data,
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
                    ["2교시 (10:00~10:50)", "", ""],
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
            "/api/codmes/data/portal",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["profile"]["student_id"] == "20260001"
    assert data["timetable"]["columns"] == ["교시", "월요일", "화요일"]
    assert data["timetable"]["rows"] == [["1교시 (09:00~09:50)", "자료구조", ""]]
    assert data["graduation"]["rows"][0] == ["전공 › 계", "60", "48", "12"]
    assert data["grade_distribution"]["summaries"][0]["fields"][0]["value"] == "4.1"
    assert data["cumulative_grades"]["tables"][0]["rows"][0] == ["2026", "자료구조", "A+"]
    assert "presentation" not in data
    assert "sections" not in data
    assert "items" not in data
    assert "systemImage" not in str(data)
