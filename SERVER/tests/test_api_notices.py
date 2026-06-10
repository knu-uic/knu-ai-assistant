import datetime
from fastapi.testclient import TestClient
from api.main import app


def test_notices_maps_rows(monkeypatch):
    fake_rows = [(
        "https://x/1", "장학금 공지", "본문내용",
        datetime.date(2026, 6, 1), datetime.date(2026, 6, 1), datetime.date(2026, 6, 12),
        "장학", ["재학생"], ["장학금", "신청"],
        "KNU", "학생지원과", "notice", None, "신청 요약",
    )]
    import api.routers.notices as m
    monkeypatch.setattr(m, "get_documents", lambda **kw: fake_rows)
    with TestClient(app) as client:
        r = client.get("/api/notices?category=장학&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["notices"]) == 1
    n = body["notices"][0]
    assert n["url"] == "https://x/1"
    assert n["title"] == "장학금 공지"
    assert n["posted_at"] == "2026-06-01"
    assert n["target"] == ["재학생"]
    assert n["keywords"] == ["장학금", "신청"]
    assert n["source_name"] == "학생지원과"


def test_notices_empty(monkeypatch):
    import api.routers.notices as m
    monkeypatch.setattr(m, "get_documents", lambda **kw: [])
    with TestClient(app) as client:
        r = client.get("/api/notices")
    assert r.status_code == 200
    assert r.json() == {"notices": []}
