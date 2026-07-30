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
    import interfaces.http.shared.notices as m
    monkeypatch.setattr(m, "get_documents", lambda **kw: fake_rows)
    monkeypatch.setattr(m, "get_account", lambda u: None)  # 미연동 → 공통, DB 미접근
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
    import interfaces.http.shared.notices as m
    monkeypatch.setattr(m, "get_documents", lambda **kw: [])
    monkeypatch.setattr(m, "get_account", lambda u: None)
    with TestClient(app) as client:
        r = client.get("/api/notices")
    assert r.status_code == 200
    assert r.json() == {"notices": [], "next_cursor": None}


def test_notices_unlinked_scopes_to_common(monkeypatch):
    """미연동 유저 → department='공통'로 조회(타과 공지 제외)."""
    import interfaces.http.shared.notices as m
    captured = {}
    monkeypatch.setattr(m, "get_documents", lambda **kw: captured.update(kw) or [])
    monkeypatch.setattr(m, "get_account", lambda u: None)
    with TestClient(app) as client:
        r = client.get("/api/notices")
    assert r.status_code == 200
    assert captured["department"] == "공통"
    assert captured["major"] is None


def test_notices_linked_scopes_to_major(monkeypatch):
    """연동 유저 → 학과로 조회(내학과+공통). major 쿼리 미지정 시 자동 해석."""
    import interfaces.http.shared.notices as m
    captured = {}
    monkeypatch.setattr(m, "get_documents", lambda **kw: captured.update(kw) or [])
    monkeypatch.setattr(m, "get_account", lambda u: {"student_id": "202202165"})
    monkeypatch.setattr(m, "get_user", lambda sid: {"major": "컴퓨터공학과"})
    with TestClient(app) as client:
        r = client.get("/api/notices")
    assert r.status_code == 200
    assert captured["major"] == "컴퓨터공학과"
    assert captured["department"] is None


def test_notices_explicit_major_query_wins(monkeypatch):
    """major 쿼리가 명시되면 자동 해석을 건너뛰고 그대로 사용(dart 호환)."""
    import interfaces.http.shared.notices as m
    captured = {}
    monkeypatch.setattr(m, "get_documents", lambda **kw: captured.update(kw) or [])
    # get_account이 호출되면 안 됨(명시 major 우선) — 호출 시 터지게
    monkeypatch.setattr(m, "get_account", lambda u: (_ for _ in ()).throw(AssertionError("called")))
    with TestClient(app) as client:
        r = client.get("/api/notices?major=경영학과")
    assert r.status_code == 200
    assert captured["major"] == "경영학과"
    assert captured["department"] is None


def _row(url: str, sort_ts: datetime.datetime):
    return (
        url, "제목", "본문",
        datetime.date(2026, 6, 1), None, None,
        "장학", [], [],
        "KNU", "학생지원과", "notice", None, None,
        sort_ts,
    )


def test_notices_next_cursor_roundtrip(monkeypatch):
    """limit보다 많으면 next_cursor 생성, 그 커서로 재요청 시 디코드 값이 DB 조회에 전달."""
    import interfaces.http.shared.notices as m

    ts = datetime.datetime(2026, 6, 1, 12, 0, 0)
    captured = {}

    def fake_get_documents(**kw):
        captured.update(kw)
        if kw["cursor_ts"] is None:
            # limit+1 = 3행 반환 → 다음 페이지 있음
            return [_row("https://x/1", ts), _row("https://x/2", ts),
                    _row("https://x/3", ts)]
        return [_row("https://x/3", ts)]

    monkeypatch.setattr(m, "get_documents", fake_get_documents)
    monkeypatch.setattr(m, "get_account", lambda u: None)

    with TestClient(app) as client:
        first = client.get("/api/notices?limit=2")
        assert first.status_code == 200
        body = first.json()
        assert len(body["notices"]) == 2
        assert body["next_cursor"] is not None

        second = client.get(f"/api/notices?limit=2&cursor={body['next_cursor']}")

    assert second.status_code == 200
    # 커서가 (마지막 행 sort_ts, url)로 풀려서 DB 조회에 들어갔는지
    assert captured["cursor_ts"] == ts
    assert captured["cursor_url"] == "https://x/2"
    assert second.json()["next_cursor"] is None  # 마지막 페이지


def test_notices_invalid_cursor_400(monkeypatch):
    import interfaces.http.shared.notices as m
    monkeypatch.setattr(m, "get_documents", lambda **kw: [])
    monkeypatch.setattr(m, "get_account", lambda u: None)
    with TestClient(app) as client:
        r = client.get("/api/notices?cursor=%%%not-base64%%%")
    assert r.status_code == 400
    assert "커서" in r.json()["detail"]
