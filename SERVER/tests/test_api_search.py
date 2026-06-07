import datetime
from fastapi.testclient import TestClient
from api.main import app


def test_search_maps_rows(monkeypatch):
    fake_rows = [(
        "https://x/9", "검색결과 공지", "스니펫 본문", 0.87,
        datetime.date(2026, 6, 2), None, None,
        "학사", ["전체"], ["수강"],
        "KNU", "학사과", "notice", None, "요약문", "바디", None,
    )]
    import api.routers.search as m
    monkeypatch.setattr(m, "embed_query", lambda q: [0.1, 0.2, 0.3])
    monkeypatch.setattr(m, "search_chunks", lambda vec, **kw: fake_rows)
    with TestClient(app) as client:
        r = client.get("/api/search?q=수강신청&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    s = body["results"][0]
    assert s["url"] == "https://x/9"
    assert s["snippet"] == "스니펫 본문"
    assert s["score"] == 0.87
    assert s["posted_at"] == "2026-06-02"
    assert s["summary"] == "요약문"


def test_search_empty(monkeypatch):
    import api.routers.search as m
    monkeypatch.setattr(m, "embed_query", lambda q: [0.0])
    monkeypatch.setattr(m, "search_chunks", lambda vec, **kw: [])
    with TestClient(app) as client:
        r = client.get("/api/search?q=없는질문")
    assert r.status_code == 200
    assert r.json() == {"results": []}
