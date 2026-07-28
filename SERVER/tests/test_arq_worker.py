import asyncio
import threading

from workers.arq_worker import WorkerSettings, _cron_minutes, poll_notices


def test_cron_minutes_interval():
    assert _cron_minutes(20) == {0, 20, 40}
    assert _cron_minutes(30) == {0, 30}
    assert _cron_minutes(10) == {0, 10, 20, 30, 40, 50}


def test_worker_has_notice_polling_cron():
    jobs = WorkerSettings.cron_jobs
    assert len(jobs) == 1
    job = jobs[0]
    assert job.coroutine is poll_notices
    # 이전 실행 미종료 시 중복 발화 방지
    assert job.unique is True
    # 기본 20분 간격 (conftest는 NOTICE_POLL_MINUTES 미설정)
    assert job.minute == {0, 20, 40}


def test_portal_sync_uses_a_fresh_thread_per_call(monkeypatch):
    import workers.arq_worker as worker_mod
    import sync.knuis_sync as knuis_sync

    class RedisStub:
        def set(self, *args, **kwargs):
            pass

        def close(self):
            pass

    event_loop_thread = threading.current_thread()
    calls = []

    def fake_run_portal_sync(student_id, password, *, on_step):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_visible = False
        else:
            loop_visible = True
        calls.append((threading.current_thread(), loop_visible))
        return {"success": False}

    monkeypatch.setattr(worker_mod.redis_sync, "from_url", lambda *_: RedisStub())
    monkeypatch.setattr(knuis_sync, "run_portal_sync", fake_run_portal_sync)
    monkeypatch.setattr("api.crypto.decrypt_secret", lambda _: "test-password")

    async def invoke_twice():
        await worker_mod.portal_sync({}, "user", "student", "encrypted")
        await worker_mod.portal_sync({}, "user", "student", "encrypted")

    asyncio.run(invoke_twice())

    assert len(calls) == 2
    assert all(thread is not event_loop_thread for thread, _ in calls)
    assert calls[0][0] is not calls[1][0]
    assert all(not loop_visible for _, loop_visible in calls)


def test_lms_sync_uses_the_same_fresh_thread_helper(monkeypatch):
    import workers.arq_worker as worker_mod

    class RedisStub:
        def set(self, *args, **kwargs):
            pass

        def close(self):
            pass

    calls = []

    def fake_lms_sync(*args):
        calls.append(threading.current_thread())
        with_loop = True
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            with_loop = False
        assert not with_loop
        return {"success": False}

    monkeypatch.setattr(worker_mod.redis_sync, "from_url", lambda *_: RedisStub())
    monkeypatch.setattr(worker_mod, "_run_lms_sync_blocking", fake_lms_sync)
    monkeypatch.setattr("api.crypto.decrypt_secret", lambda _: "test-password")

    asyncio.run(worker_mod.lms_sync({}, "user", "student", "encrypted"))
    assert len(calls) == 1
