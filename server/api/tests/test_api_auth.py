import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_legacy_service_account_routes_are_removed():
    with TestClient(app) as client:
        assert client.post("/api/auth/signup/request", json={}).status_code == 404
        assert client.post("/api/auth/signup/verify", json={}).status_code == 404
        assert client.post("/api/auth/login", json={}).status_code == 404


def test_portal_login_issues_direct_student_token(monkeypatch):
    import jwt
    import api.sessions as sessions
    import sync.portal_auth as portal_auth

    synced = []
    saved = []
    saved_sessions = []
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
    monkeypatch.setattr(
        sessions,
        "save_portal_session",
        lambda sid, state: saved_sessions.append((sid, state)),
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
    assert saved_sessions == [("20260001", {"cookies": [], "origins": []})]


@pytest.mark.real_auth
def test_portal_logout_revokes_only_the_presented_session(monkeypatch):
    from api.deps import create_portal_access_token, decode_access_token
    import api.sessions as sessions

    deleted = []
    monkeypatch.setattr(sessions, "delete_portal_session", deleted.append)

    first = create_portal_access_token("20260001")
    second = create_portal_access_token("20260001")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {first}"},
        )

    assert response.status_code == 200
    assert response.json() == {"logged_out": True, "session_revoked": True}
    assert deleted == ["20260001"]
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
    from api.deps import create_portal_access_token

    monkeypatch.setattr(notices_mod, "get_documents", lambda **kw: [])
    monkeypatch.setattr(notices_mod, "get_user", lambda sid: None)
    token = create_portal_access_token("20260001")

    with TestClient(app) as client:
        r = client.get("/api/notices", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200


@pytest.mark.real_auth
def test_health_stays_public():
    with TestClient(app) as client:
        r = client.get("/api/health")

    assert r.status_code == 200
