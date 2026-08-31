import pytest
from fastapi.testclient import TestClient

from api.main import app


SCHOOL_EMAIL = "student1@smail.kongju.ac.kr"


def _request_code(client, email=SCHOOL_EMAIL):
    return client.post("/api/auth/signup/request", json={"email": email})


def _verify(client, email=SCHOOL_EMAIL, code="123456",
            username="student1", password="password123"):
    return client.post(
        "/api/auth/signup/verify",
        json={"email": email, "code": code, "username": username, "password": password},
    )


def test_signup_request_rejects_non_school_email():
    with TestClient(app) as client:
        r = _request_code(client, email="attacker@gmail.com")

    assert r.status_code == 400


def test_signup_request_sends_code(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    sent = {}
    monkeypatch.setattr(auth_mod, "last_verification_at", lambda e: None)
    monkeypatch.setattr(auth_mod, "insert_verification", lambda e, c, exp: sent.update(code=c))
    monkeypatch.setattr(
        auth_mod, "send_verification_email", lambda to, code: sent.update(to=to)
    )

    with TestClient(app) as client:
        r = _request_code(client)

    assert r.status_code == 200
    assert r.json() == {"sent": True}
    assert sent["to"] == SCHOOL_EMAIL
    assert len(sent["code"]) == 6 and sent["code"].isdigit()


def test_signup_request_cooldown_429(monkeypatch):
    from datetime import datetime, timezone

    import interfaces.http.shared.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "last_verification_at", lambda e: datetime.now(timezone.utc)
    )

    with TestClient(app) as client:
        r = _request_code(client)

    assert r.status_code == 429


def test_signup_request_mail_failure_502(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    monkeypatch.setattr(auth_mod, "last_verification_at", lambda e: None)
    monkeypatch.setattr(auth_mod, "insert_verification", lambda e, c, exp: None)

    def boom(to, code):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(auth_mod, "send_verification_email", boom)

    with TestClient(app) as client:
        r = _request_code(client)

    assert r.status_code == 502


def test_signup_verify_creates_account(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_account", lambda u: None)
    monkeypatch.setattr(auth_mod, "consume_verification", lambda e, c: True)
    monkeypatch.setattr(auth_mod, "create_account", lambda u, h, e: True)

    with TestClient(app) as client:
        r = _verify(client)

    assert r.status_code == 201
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_signup_verify_bad_code_400(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_account", lambda u: None)
    monkeypatch.setattr(auth_mod, "consume_verification", lambda e, c: False)

    with TestClient(app) as client:
        r = _verify(client, code="000000")

    assert r.status_code == 400


def test_signup_verify_duplicate_username_409_before_code_consumed(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    consumed = []
    monkeypatch.setattr(auth_mod, "get_account", lambda u: {"username": u})
    monkeypatch.setattr(
        auth_mod, "consume_verification", lambda e, c: consumed.append(1) or True
    )

    with TestClient(app) as client:
        r = _verify(client)

    assert r.status_code == 409
    # 중복 아이디로 코드가 소비돼 날아가면 안 됨
    assert consumed == []


def test_login_success_and_wrong_password(monkeypatch):
    import bcrypt
    import jwt

    import interfaces.http.shared.auth as auth_mod

    password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    account = {
        "id": 1,
        "username": "student1",
        "password_hash": password_hash,
        "student_id": None,
    }
    monkeypatch.setattr(auth_mod, "get_account", lambda u: account)

    with TestClient(app) as client:
        ok = client.post(
            "/api/auth/login",
            json={"username": "student1", "password": "password123"},
        )
        bad = client.post(
            "/api/auth/login",
            json={"username": "student1", "password": "wrong-password"},
        )

    assert ok.status_code == 200
    token = ok.json()["access_token"]
    assert token
    assert "exp" not in jwt.decode(token, options={"verify_signature": False})
    assert bad.status_code == 401


def test_login_unknown_username_401(monkeypatch):
    import interfaces.http.shared.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_account", lambda u: None)

    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "password123"},
        )

    assert r.status_code == 401


def test_portal_login_issues_direct_student_token(monkeypatch):
    import jwt
    import sync.portal_auth as portal_auth

    synced = []
    saved = []
    monkeypatch.setattr(
        portal_auth,
        "authenticate_portal",
        lambda sid, pw: {
            "storage_state": {"cookies": [], "origins": []},
            "profile": {
                "name": "테스트 학생",
                "major": "컴퓨터공학과",
                "academic_status": "학부생",
            },
        },
    )
    monkeypatch.setattr(portal_auth, "mark_portal_sync_started", lambda sid: None)
    monkeypatch.setattr(
        portal_auth,
        "save_portal_identity",
        lambda sid, profile: saved.append((sid, profile)),
    )
    monkeypatch.setattr(
        portal_auth,
        "sync_university_data",
        lambda sid, state, password, profile: synced.append(
            (sid, state, password, profile)
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login",
            json={"student_id": "20260001", "password": "portal-password"},
        )

    assert response.status_code == 200
    payload = jwt.decode(
        response.json()["access_token"],
        options={"verify_signature": False},
    )
    assert payload["sub"] == "portal:20260001"
    assert payload["sid"]
    assert "exp" not in payload
    assert saved == [(
        "20260001",
        {
            "name": "테스트 학생",
            "major": "컴퓨터공학과",
            "academic_status": "학부생",
        },
    )]
    assert synced == [(
        "20260001",
        {"cookies": [], "origins": []},
        "portal-password",
        {
            "name": "테스트 학생",
            "major": "컴퓨터공학과",
            "academic_status": "학부생",
        },
    )]


@pytest.mark.real_auth
def test_portal_logout_revokes_only_the_presented_session():
    from api.deps import create_portal_access_token, decode_access_token

    first = create_portal_access_token("20260001")
    second = create_portal_access_token("20260001")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {first}"},
        )

    assert response.status_code == 200
    assert response.json() == {"logged_out": True, "session_revoked": True}
    with pytest.raises(Exception, match="로그아웃되었거나"):
        decode_access_token(first)
    assert decode_access_token(second) == "portal:20260001"


def test_portal_login_rejects_invalid_credentials(monkeypatch):
    import sync.portal_auth as portal_auth

    monkeypatch.setattr(portal_auth, "authenticate_portal", lambda sid, pw: None)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login",
            json={"student_id": "20260001", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert "포털" in response.json()["detail"]


def test_portal_login_surfaces_password_lock_reason(monkeypatch):
    import sync.portal_auth as portal_auth

    def reject_locked_account(_student_id, _password):
        raise portal_auth.PortalLoginRejected(
            "공주대 포털의 비밀번호 오류 횟수가 5회 이상입니다. "
            "포털에서 비밀번호를 변경한 후 다시 시도해주세요."
        )

    monkeypatch.setattr(
        portal_auth,
        "authenticate_portal",
        reject_locked_account,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login",
            json={"student_id": "20260001", "password": "locked-password"},
        )

    assert response.status_code == 401
    assert "5회 이상" in response.json()["detail"]
    assert "변경한 후" in response.json()["detail"]


def test_university_sync_runs_portal_and_lms_without_persisting_password(monkeypatch):
    import sync.knuis_sync as knuis_sync
    import sync.portal_auth as portal_auth

    calls = []
    monkeypatch.setattr(
        knuis_sync,
        "run_portal_sync",
        lambda sid, **kwargs: calls.append(("portal", sid)) or {"success": True},
    )
    monkeypatch.setattr(
        portal_auth,
        "sync_lms_data",
        lambda sid, password: calls.append(("lms", sid, password)) or {"success": True},
    )

    result = portal_auth.sync_university_data(
        "20260001",
        {"cookies": [], "origins": []},
        "one-time-password",
    )

    assert result["portal"]["success"] is True
    assert result["lms"]["success"] is True
    assert calls == [
        ("portal", "20260001"),
        ("lms", "20260001", "one-time-password"),
    ]
    assert portal_auth.portal_sync_status("20260001")["syncing"] is False


def test_university_sync_preserves_portal_failure_for_status_api(monkeypatch):
    import sync.knuis_sync as knuis_sync
    import sync.portal_auth as portal_auth

    monkeypatch.setattr(
        knuis_sync,
        "run_portal_sync",
        lambda sid, **kwargs: {
            "success": False,
            "message": "통합정보시스템 진입 버튼을 찾지 못했습니다.",
        },
    )
    monkeypatch.setattr(
        portal_auth,
        "sync_lms_data",
        lambda sid, password: {"success": True},
    )

    portal_auth.sync_university_data(
        "20260002",
        {"cookies": [], "origins": []},
        "one-time-password",
    )

    status = portal_auth.portal_sync_status("20260002")
    assert status["syncing"] is False
    assert status["portal_error"] == "통합정보시스템 진입 버튼을 찾지 못했습니다."

    portal_auth.mark_portal_sync_started("20260002")
    assert portal_auth.portal_sync_status("20260002")["portal_error"] is None


@pytest.mark.real_auth
def test_public_notices_allow_anonymous_but_reject_invalid_token(monkeypatch):
    import interfaces.http.shared.notices as notices_mod

    monkeypatch.setattr(notices_mod, "get_documents", lambda **kw: [])

    with TestClient(app) as client:
        no_token = client.get("/api/notices")
        bad_token = client.get(
            "/api/notices", headers={"Authorization": "Bearer not-a-jwt"}
        )

    assert no_token.status_code == 200
    assert bad_token.status_code == 401


@pytest.mark.real_auth
def test_protected_route_accepts_valid_token(monkeypatch):
    import interfaces.http.shared.notices as notices_mod
    from api.deps import create_access_token

    monkeypatch.setattr(notices_mod, "get_documents", lambda **kw: [])
    monkeypatch.setattr(notices_mod, "get_account", lambda u: None)
    token = create_access_token("student1")

    with TestClient(app) as client:
        r = client.get("/api/notices", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200


@pytest.mark.real_auth
def test_health_stays_public():
    with TestClient(app) as client:
        r = client.get("/api/health")

    assert r.status_code == 200
