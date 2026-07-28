import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.crypto import decrypt_secret


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
    import api.routers.auth as auth_mod

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

    import api.routers.auth as auth_mod

    monkeypatch.setattr(
        auth_mod, "last_verification_at", lambda e: datetime.now(timezone.utc)
    )

    with TestClient(app) as client:
        r = _request_code(client)

    assert r.status_code == 429


def test_signup_request_mail_failure_502(monkeypatch):
    import api.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod, "last_verification_at", lambda e: None)
    monkeypatch.setattr(auth_mod, "insert_verification", lambda e, c, exp: None)

    def boom(to, code):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(auth_mod, "send_verification_email", boom)

    with TestClient(app) as client:
        r = _request_code(client)

    assert r.status_code == 502


def test_signup_verify_creates_account(monkeypatch):
    import api.routers.auth as auth_mod

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
    import api.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_account", lambda u: None)
    monkeypatch.setattr(auth_mod, "consume_verification", lambda e, c: False)

    with TestClient(app) as client:
        r = _verify(client, code="000000")

    assert r.status_code == 400


def test_signup_verify_duplicate_username_409_before_code_consumed(monkeypatch):
    import api.routers.auth as auth_mod

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

    import api.routers.auth as auth_mod

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
    import api.routers.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_account", lambda u: None)

    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "password123"},
        )

    assert r.status_code == 401


class _PortalLoginPool:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))


def _patch_portal_login_pool(monkeypatch, pool):
    import api.routers.auth as auth_mod

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(auth_mod, "get_arq_pool", fake_get_pool)
    return auth_mod


def test_portal_login_enqueues_existing_worker_with_short_expiry(monkeypatch):
    pool = _PortalLoginPool()
    auth_mod = _patch_portal_login_pool(monkeypatch, pool)

    import sync.portal_auth as portal_auth

    monkeypatch.setattr(
        portal_auth,
        "authenticate_portal",
        lambda *_: (_ for _ in ()).throw(AssertionError("direct portal auth")),
    )
    monkeypatch.setattr(
        portal_auth,
        "sync_university_data",
        lambda *_: (_ for _ in ()).throw(AssertionError("direct background sync")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login",
            json={"student_id": "20260001", "password": "portal-password"},
        )

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"job_id"}
    assert len(body["job_id"]) >= 32
    assert "portal-password" not in response.text
    fn, args, kwargs = pool.calls[0]
    assert fn == "portal_sync"
    assert args[0] == "portal:20260001"
    assert args[1] == "20260001"
    assert decrypt_secret(args[2]) == "portal-password"
    assert args[2] != "portal-password"
    assert kwargs["_job_id"] == body["job_id"]
    assert kwargs["_expires"] <= 210


class _PortalJobInfo:
    function = "portal_sync"
    args = ("portal:20260001", "20260001", "encrypted-password")
    success = True
    result = {"success": True}


class _PortalLoginJob:
    status_value = None
    info_value = _PortalJobInfo()

    def __init__(self, job_id, redis=None):
        self.job_id = job_id

    async def status(self):
        return self.status_value

    async def info(self):
        return self.info_value


def _patch_portal_status(monkeypatch, status, info):
    from arq.jobs import JobStatus

    import api.routers.auth as auth_mod

    pool = _PortalLoginPool()
    _patch_portal_login_pool(monkeypatch, pool)
    _PortalLoginJob.status_value = JobStatus(status)
    _PortalLoginJob.info_value = info
    monkeypatch.setattr(auth_mod, "Job", _PortalLoginJob)


@pytest.mark.parametrize(
    ("arq_status", "expected"),
    [("deferred", "queued"), ("queued", "queued"), ("in_progress", "running")],
)
def test_portal_login_status_maps_queued_and_running(monkeypatch, arq_status, expected):
    _patch_portal_status(monkeypatch, arq_status, _PortalJobInfo())

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "known-job"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": expected}
    assert "access_token" not in response.text


def test_portal_login_status_maps_worker_failure_to_generic_failed(monkeypatch):
    class FailedInfo(_PortalJobInfo):
        success = False
        result = RuntimeError("portal-password leaked")

    _patch_portal_status(monkeypatch, "complete", FailedInfo())

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "known-job"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "detail": "포털 로그인에 실패했습니다. 잠시 후 다시 시도해주세요.",
    }
    assert "portal-password" not in response.text
    assert "access_token" not in response.text


def test_portal_login_status_maps_portal_failure_to_generic_failed(monkeypatch):
    class FailedPortalInfo(_PortalJobInfo):
        result = {"success": False, "message": "portal-password"}

    _patch_portal_status(monkeypatch, "complete", FailedPortalInfo())

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "known-job"}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "portal-password" not in response.text
    assert "access_token" not in response.text


def test_portal_login_status_maps_invalid_credentials_without_leaking_result(monkeypatch):
    import api.routers.auth as auth_mod

    class InvalidCredentialsInfo(_PortalJobInfo):
        result = {
            "success": False,
            "error_code": "invalid_credentials",
            "message": "아이디/비밀번호 불일치: portal-password; dialog=credential mismatch",
        }

    _patch_portal_status(monkeypatch, "complete", InvalidCredentialsInfo())

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "known-job"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "detail": auth_mod.PORTAL_LOGIN_INVALID_CREDENTIALS_DETAIL,
    }
    assert "portal-password" not in response.text
    assert "credential mismatch" not in response.text
    assert "아이디/비밀번호 불일치" not in response.text


def test_portal_login_status_issues_jwt_only_for_successful_matching_done_job(monkeypatch):
    import jwt

    _patch_portal_status(monkeypatch, "complete", _PortalJobInfo())

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "known-job"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["token_type"] == "bearer"
    payload = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert payload["sub"] == "portal:20260001"


@pytest.mark.parametrize(
    "info",
    [
        None,
        type("OtherJob", (), {"function": "lms_sync", "args": ("portal:20260001", "20260001")})(),
        type("WrongUser", (), {"function": "portal_sync", "args": ("other", "20260001")})(),
        type("WrongStudent", (), {"function": "portal_sync", "args": ("portal:20260001", "20260002")})(),
    ],
)
def test_portal_login_status_rejects_unknown_expired_or_misidentified_jobs(monkeypatch, info):
    _patch_portal_status(monkeypatch, "not_found" if info is None else "complete", info)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/portal-login/status", json={"job_id": "unknown-job"}
        )

    assert response.status_code == 404
    assert "access_token" not in response.text


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


@pytest.mark.real_auth
def test_public_notices_allow_anonymous_but_reject_invalid_token(monkeypatch):
    import api.routers.notices as notices_mod

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
    import api.routers.notices as notices_mod
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
