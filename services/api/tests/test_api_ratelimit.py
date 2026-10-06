import pytest
from fastapi.testclient import TestClient

from api.main import app

@pytest.mark.real_rate_limit
def test_429_detail_is_korean(monkeypatch):
    import sync.portal_auth as portal_auth

    monkeypatch.setattr(portal_auth, "authenticate_portal", lambda sid, pw: None)
    with TestClient(app) as client:
        for _ in range(10):
            client.post(
                "/api/auth/portal-login",
                json={"student_id": "20260001", "password": "wrong"},
            )
        r = client.post(
            "/api/auth/portal-login",
            json={"student_id": "20260001", "password": "wrong"},
        )

    assert r.status_code == 429
    assert r.json()["detail"] == "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."


@pytest.mark.real_rate_limit
@pytest.mark.real_auth
def test_chat_limit_is_per_user(monkeypatch):
    """기본 상한 5/minute — 유저 A가 소진해도 유저 B는 통과(키 = JWT sub)."""
    import interfaces.http.web.chat as chat_mod
    from api.deps import create_portal_access_token

    async def fake_answer(student_id, question, history):
        return "ok"

    monkeypatch.setattr(chat_mod, "answer", fake_answer)

    def _headers(student_id):
        return {"Authorization": f"Bearer {create_portal_access_token(student_id)}"}

    with TestClient(app) as client:
        a_statuses = [
            client.post(
                "/api/chat", json={"question": "q"}, headers=_headers("20260001")
            ).status_code
            for _ in range(6)
        ]
        b_status = client.post(
            "/api/chat", json={"question": "q"}, headers=_headers("20260002")
        ).status_code

    assert a_statuses[:5] == [200] * 5
    assert a_statuses[5] == 429
    assert b_status == 200
