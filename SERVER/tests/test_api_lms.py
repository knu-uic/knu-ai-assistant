import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.crypto import decrypt_secret

USER_JOB_ID = "lms-sync:testuser"


class FakePool:
    def __init__(self):
        self.calls = []
        self.deleted = []

    async def enqueue_job(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return object()

    async def get(self, key):
        return "할 일 동기화 중".encode()

    async def delete(self, *keys):
        self.deleted.extend(keys)


class _StartJob:
    """start 핸들러의 dedup 상태 확인용 — 기본은 '이전 잡 없음'(complete)."""

    from arq.jobs import JobStatus as _JS
    _status = _JS.complete

    def __init__(self, job_id, redis=None):
        pass

    async def status(self):
        return self._status


def _patch_pool(monkeypatch, pool, start_job=_StartJob):
    import api.routers.lms as lms_mod

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(lms_mod, "get_arq_pool", fake_get_pool)
    # start 핸들러가 dedup 판정에 쓰는 Job — status 테스트는 자체 FakeJob으로 덮어쓴다.
    monkeypatch.setattr(lms_mod, "Job", start_job)
    return lms_mod


def test_start_without_password_enqueues_none(monkeypatch):
    pool = FakePool()
    _patch_pool(monkeypatch, pool)

    with TestClient(app) as client:
        r = client.post("/api/lms/sync/start", json={"student_id": "20231234"})

    assert r.status_code == 202
    assert r.json() == {"job_id": USER_JOB_ID}
    fn, args, kwargs = pool.calls[0]
    assert fn == "lms_sync"
    username, student_id, enc_password = args
    assert username == "testuser"
    assert enc_password is None  # 비번 없는 세션 재사용 경로


def test_start_with_password_encrypts(monkeypatch):
    pool = FakePool()
    _patch_pool(monkeypatch, pool)

    with TestClient(app) as client:
        r = client.post(
            "/api/lms/sync/start",
            json={"student_id": "20231234", "password": "lms-pw"},
        )

    assert r.status_code == 202
    _, args, _ = pool.calls[0]
    enc_password = args[2]
    assert enc_password != "lms-pw"
    assert decrypt_secret(enc_password) == "lms-pw"


def test_start_dedup_while_in_progress(monkeypatch):
    """진행 중인 잡이 있으면 새로 enqueue·delete 하지 않고 같은 job_id 반환."""
    from arq.jobs import JobStatus

    class InProgressJob(_StartJob):
        _status = JobStatus.in_progress

    pool = FakePool()
    _patch_pool(monkeypatch, pool, start_job=InProgressJob)

    with TestClient(app) as client:
        r = client.post("/api/lms/sync/start", json={"student_id": "20231234"})

    assert r.status_code == 202
    assert r.json() == {"job_id": USER_JOB_ID}
    assert pool.calls == []  # 재실행 안 함
    assert pool.deleted == []  # 결과 안 지움


def test_start_completed_job_reruns(monkeypatch):
    """완료된 이전 잡은 결과를 지우고 새로 실행 (needs_reconnect 후 재시도 보장)."""
    pool = FakePool()
    _patch_pool(monkeypatch, pool)  # 기본 _StartJob = complete

    with TestClient(app) as client:
        r = client.post(
            "/api/lms/sync/start",
            json={"student_id": "20231234", "password": "pw"},
        )

    assert r.status_code == 202
    assert pool.deleted == [f"arq:result:{USER_JOB_ID}"]  # stale 결과 제거
    assert len(pool.calls) == 1  # 재실행


def test_status_rejects_other_users_job(monkeypatch):
    _patch_pool(monkeypatch, FakePool())
    with TestClient(app) as client:
        r = client.get("/api/lms/sync/lms-sync:someone-else")
    assert r.status_code == 404


class FakeJob:
    def __init__(self, job_id, redis=None):
        pass

    async def status(self):
        return self._status

    async def result_info(self):
        return self._info


def test_status_running_shows_step(monkeypatch):
    from arq.jobs import JobStatus

    lms_mod = _patch_pool(monkeypatch, FakePool())
    FakeJob._status = JobStatus.in_progress
    FakeJob._info = None
    monkeypatch.setattr(lms_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/lms/sync/{USER_JOB_ID}")

    body = r.json()
    assert body["status"] == "running"
    assert body["step"] == "할 일 동기화 중"


def test_status_done_returns_result(monkeypatch):
    from arq.jobs import JobStatus

    lms_mod = _patch_pool(monkeypatch, FakePool())

    class Info:
        success = True
        result = {"success": True, "message": "ok", "course_count": 5}

    FakeJob._status = JobStatus.complete
    FakeJob._info = Info()
    monkeypatch.setattr(lms_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/lms/sync/{USER_JOB_ID}")

    body = r.json()
    assert body["status"] == "done"
    assert body["result"]["course_count"] == 5


def test_status_needs_reconnect_flag(monkeypatch):
    from arq.jobs import JobStatus

    lms_mod = _patch_pool(monkeypatch, FakePool())

    class Info:
        success = True
        result = {"success": False, "needs_reconnect": True, "message": "세션 만료"}

    FakeJob._status = JobStatus.complete
    FakeJob._info = Info()
    monkeypatch.setattr(lms_mod, "Job", FakeJob)

    with TestClient(app) as client:
        r = client.get(f"/api/lms/sync/{USER_JOB_ID}")

    body = r.json()
    assert body["status"] == "failed"
    assert body["needs_reconnect"] is True


def test_session_store_roundtrip(monkeypatch):
    """save_session → load_session 왕복 (Redis는 fake로 대체, 암호화 경로 검증)."""
    import api.sessions as sessions_mod

    store = {}

    class FakeRedis:
        def get(self, k):
            return store.get(k)

        def set(self, k, v, ex=None):
            store[k] = v.encode() if isinstance(v, str) else v

        def close(self):
            pass

    monkeypatch.setattr(sessions_mod, "_client", lambda: FakeRedis())

    sessions_mod.save_session("u1", '{"cookies": []}', "canvas-tok")
    # 저장된 값은 암호문이어야 함 (평문 노출 금지)
    assert b'"cookies"' not in store["lms-session:u1"]

    loaded = sessions_mod.load_session("u1")
    assert loaded["storage_state"] == '{"cookies": []}'
    assert loaded["canvas_token"] == "canvas-tok"
    assert sessions_mod.load_session("nobody") is None
