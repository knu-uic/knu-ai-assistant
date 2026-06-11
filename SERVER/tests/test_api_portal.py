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
        self.deleted = []
        self.enqueue_result = enqueue_result

    async def enqueue_job(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return None if self.enqueue_result is None else object()

    async def get(self, key):
        return "시간표 가져오는 중".encode()

    async def delete(self, *keys):
        self.deleted.extend(keys)


class _StartJob:
    """start 핸들러 dedup 판정용 — 기본은 '이전 잡 없음'(complete)."""

    from arq.jobs import JobStatus as _JS
    _status = _JS.complete

    def __init__(self, job_id, redis=None):
        pass

    async def status(self):
        return self._status


def _patch_pool(monkeypatch, pool, start_job=_StartJob):
    import api.routers.portal as portal_mod

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(portal_mod, "get_arq_pool", fake_get_pool)
    monkeypatch.setattr(portal_mod, "Job", start_job)
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


def test_start_dedup_while_in_progress(monkeypatch):
    # 진행 중인 잡이 있으면 새로 enqueue·delete 안 하고 같은 job_id 반환
    from arq.jobs import JobStatus

    class InProgressJob(_StartJob):
        _status = JobStatus.in_progress

    pool = FakePool()
    _patch_pool(monkeypatch, pool, start_job=InProgressJob)

    with TestClient(app) as client:
        r = client.post(
            "/api/portal/sync/start",
            json={"student_id": "20231234", "password": "portal-pw"},
        )

    assert r.status_code == 202
    assert r.json()["job_id"] == USER_JOB_ID
    assert pool.calls == []
    assert pool.deleted == []


def test_start_completed_job_reruns(monkeypatch):
    # 완료된 이전 잡은 결과를 지우고 새로 실행
    pool = FakePool()
    _patch_pool(monkeypatch, pool)  # 기본 _StartJob = complete

    with TestClient(app) as client:
        r = client.post(
            "/api/portal/sync/start",
            json={"student_id": "20231234", "password": "portal-pw"},
        )

    assert r.status_code == 202
    assert pool.deleted == [f"arq:result:{USER_JOB_ID}"]
    assert len(pool.calls) == 1


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
