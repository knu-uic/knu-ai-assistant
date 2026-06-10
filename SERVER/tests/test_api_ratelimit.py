import pytest
from fastapi.testclient import TestClient

from api.main import app

SCHOOL_EMAIL = "limituser@smail.kongju.ac.kr"


def _mock_signup_request_deps(monkeypatch):
    import api.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod, "last_verification_at", lambda e: None)
    monkeypatch.setattr(auth_mod, "insert_verification", lambda e, c, exp: None)
    monkeypatch.setattr(auth_mod, "send_verification_email", lambda to, code: None)


@pytest.mark.real_rate_limit
def test_signup_request_ip_limit_429(monkeypatch):
    """기본 상한 3/minute — 같은 IP 4번째 호출은 429."""
    _mock_signup_request_deps(monkeypatch)

    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/auth/signup/request", json={"email": SCHOOL_EMAIL}
            ).status_code
            for _ in range(4)
        ]

    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


@pytest.mark.real_rate_limit
def test_429_detail_is_korean(monkeypatch):
    _mock_signup_request_deps(monkeypatch)

    with TestClient(app) as client:
        for _ in range(3):
            client.post("/api/auth/signup/request", json={"email": SCHOOL_EMAIL})
        r = client.post("/api/auth/signup/request", json={"email": SCHOOL_EMAIL})

    assert r.status_code == 429
    assert r.json()["detail"] == "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."


@pytest.mark.real_rate_limit
@pytest.mark.real_auth
def test_chat_limit_is_per_user(monkeypatch):
    """기본 상한 5/minute — 유저 A가 소진해도 유저 B는 통과(키 = JWT sub)."""
    import api.routers.chat as chat_mod
    from api.deps import create_access_token

    class FakeGraph:
        def invoke(self, state):
            return {"answer": "ok"}

    monkeypatch.setattr(chat_mod, "GRAPH", FakeGraph())

    def _headers(username):
        return {"Authorization": f"Bearer {create_access_token(username)}"}

    with TestClient(app) as client:
        a_statuses = [
            client.post(
                "/api/chat", json={"question": "q"}, headers=_headers("user-a")
            ).status_code
            for _ in range(6)
        ]
        b_status = client.post(
            "/api/chat", json={"question": "q"}, headers=_headers("user-b")
        ).status_code

    assert a_statuses[:5] == [200] * 5
    assert a_statuses[5] == 429
    assert b_status == 200


def test_limits_disabled_in_normal_tests(monkeypatch):
    """autouse fixture가 limiter를 꺼서 일반 테스트는 호출 누적과 무관하게 통과."""
    _mock_signup_request_deps(monkeypatch)

    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/auth/signup/request", json={"email": SCHOOL_EMAIL}
            ).status_code
            for _ in range(5)
        ]

    assert statuses == [200] * 5
