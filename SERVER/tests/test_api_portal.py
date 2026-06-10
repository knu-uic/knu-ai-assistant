import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.crypto import decrypt_secret, encrypt_secret

# bypass_auth fixture가 require_user를 "testuser"로 대체한다
USER_JOB_ID = "portal-sync:testuser"


def test_crypto_roundtrip():
    token = encrypt_secret("my-portal-pw")
    assert token != "my-portal-pw"
    assert decrypt_secret(token) == "my-portal-pw"


class FakePool:
    def __init__(self, enqueue_result="job"):
        self.calls = []
        self.enqueue_result = enqueue_result

    async def enqueue_job(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return None if self.enqueue_result is None else object()

    async def get(self, key):
        return "시간표 가져오는 중".encode()


def _patch_pool(monkeypatch, pool):
    import api.routers.portal as portal_mod

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(portal_mod, "get_arq_pool", fake_get_pool)
    return portal_mod


def test_start_enqueues_encrypted_password(monkeypatch):
    pool = FakePool()
    _patch_pool(monkeypatch, pool)

    with TestClient(app) as client:
        r = client.post(
            "/api/portal/sync/start",
            json={"student_id": "20231234", "password": "portal-pw"},
        )

    assert r.status_code == 202
    assert r.json() == {"job_id": USER_JOB_ID}

    fn, args, kwargs = pool.calls[0]
    assert fn == "portal_sync"
    username, student_id, enc_password = args
    assert username == "testuser"
    assert student_id == "20231234"
    # 평문 비번이 잡 페이로드에 실리면 안 됨 — 복호화로만 원문 확인
    assert enc_password != "portal-pw"
    assert decrypt_secret(enc_password) == "portal-pw"
    assert kwargs["_job_id"] == USER_JOB_ID


def test_start_duplicate_returns_same_job_id(monkeypatch):
    # enqueue_job이 None(이미 존재) → 새 잡 안 만들고 같은 job_id 반환
    pool = FakePool(enqueue_result=None)
    _patch_pool(monkeypatch, pool)

    with TestClient(app) as client:
        r = client.post(
            "/api/portal/sync/start",
            json={"student_id": "20231234", "password": "portal-pw"},
        )

    assert r.status_code == 202
    assert r.json()["job_id"] == USER_JOB_ID


def test_status_rejects_other_users_job(monkeypatch):
    _patch_pool(monkeypatch, FakePool())

    with TestClient(app) as client:
        r = client.get("/api/portal/sync/portal-sync:someone-else")

    assert r.status_code == 404


class FakeJob:
    def __init__(self, job_id, redis=None):
        pass

    async def status(self):
        return self._status

    async def result_info(self):
        return self._info


@pytest.mark.parametrize(
    "arq_status,expected",
    [("queued", "queued"), ("in_progress", "running")],
)
def test_status_mapping(monkeypatch, arq_status, expected):
    from arq.jobs import JobStatus

    portal_mod = _patch_pool(monkeypatch, FakePool())
    FakeJob._status = JobStatus(arq_status)
    FakeJob._info = None
    monkeypatch.setattr(portal_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/portal/sync/{USER_JOB_ID}")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == expected
    if expected == "running":
        assert body["step"] == "시간표 가져오는 중"


def test_status_done_returns_result(monkeypatch):
    from arq.jobs import JobStatus

    portal_mod = _patch_pool(monkeypatch, FakePool())

    class Info:
        success = True
        result = {"success": True, "message": "ok", "timetable_synced": True}

    FakeJob._status = JobStatus.complete
    FakeJob._info = Info()
    monkeypatch.setattr(portal_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/portal/sync/{USER_JOB_ID}")

    body = r.json()
    assert body["status"] == "done"
    assert body["result"]["timetable_synced"] is True


def test_status_job_crash_maps_to_failed(monkeypatch):
    from arq.jobs import JobStatus

    portal_mod = _patch_pool(monkeypatch, FakePool())

    class Info:
        success = False
        result = None

    FakeJob._status = JobStatus.complete
    FakeJob._info = Info()
    monkeypatch.setattr(portal_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/portal/sync/{USER_JOB_ID}")

    body = r.json()
    assert body["status"] == "failed"
    assert "실패" in body["detail"]
