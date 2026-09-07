import asyncio

from workers.arq_worker import (
    WorkerSettings,
    counseling_prepare,
    counseling_submit,
    keep_portal_session,
    poll_notices,
    scheduled_portal_keepalive,
    scheduled_poll_notices,
)
from workers import arq_worker


def test_worker_has_notice_polling_cron():
    jobs = WorkerSettings.cron_jobs
    job = next(job for job in jobs if job.coroutine is scheduled_poll_notices)
    assert job.coroutine is scheduled_poll_notices
    # 이전 실행 미종료 시 중복 발화 방지
    assert job.unique is True
    # 매시 정각에 runtime setting(1/6/12/24시간)을 확인한다.
    assert job.minute == {0}


def test_worker_has_portal_keepalive_cron():
    job = next(job for job in WorkerSettings.cron_jobs if job.coroutine is scheduled_portal_keepalive)

    assert job.unique is True
    assert job.minute == set(range(0, 60, 10))


def test_manual_notice_poll_is_registered():
    registered = next(item for item in WorkerSettings.functions if getattr(item, "name", "") == "poll_notices")
    assert registered.coroutine is poll_notices
    assert registered.timeout_s == 21600


def test_scheduled_poll_uses_recent_seven_day_scope(monkeypatch):
    received = []

    async def fake_poll(ctx, request):
        received.append((ctx, request))
        return {"ok": True}

    configured_request = {
        "mode": "range",
        "start_page": 2,
        "end_page": 4,
        "recent_days": 7,
        "refresh_outdated_extraction": True,
        "source_codes": ["cse_notice"],
    }
    monkeypatch.setattr(arq_worker, "load_settings", lambda: {
        "crawl_enabled": True,
        "crawl_interval_hours": 1,
        "crawl_request": configured_request,
    })
    monkeypatch.setattr(arq_worker, "poll_notices", fake_poll)

    result = asyncio.run(arq_worker.scheduled_poll_notices({"job_id": "scheduled"}))

    assert result == {"ok": True}
    assert received[0][1] == configured_request


def test_scheduled_poll_skips_when_automatic_crawl_is_disabled(monkeypatch):
    called = False

    async def fake_poll(_ctx, _request):
        nonlocal called
        called = True

    monkeypatch.setattr(arq_worker, "load_settings", lambda: {"crawl_enabled": False, "crawl_interval_hours": 1})
    monkeypatch.setattr(arq_worker, "poll_notices", fake_poll)

    result = asyncio.run(arq_worker.scheduled_poll_notices({"job_id": "scheduled"}))

    assert result == {"skipped": True, "reason": "automatic_crawl_disabled"}
    assert called is False


def test_worker_registers_counseling_jobs():
    assert counseling_prepare in WorkerSettings.functions
    assert counseling_submit in WorkerSettings.functions
    assert keep_portal_session in WorkerSettings.functions


def test_scheduled_portal_keepalive_refreshes_each_stored_session(monkeypatch):
    calls = []

    monkeypatch.setattr(arq_worker, "portal_session_student_ids", lambda: ["20260001", "20260002"], raising=False)

    async def fake_keepalive(ctx, student_id):
        calls.append((ctx, student_id))
        return {"success": student_id == "20260001", "needs_reconnect": student_id == "20260002"}

    monkeypatch.setattr(arq_worker, "keep_portal_session", fake_keepalive)
    import api.sessions as sessions

    monkeypatch.setattr(sessions, "portal_session_student_ids", lambda: ["20260001", "20260002"])
    result = asyncio.run(arq_worker.scheduled_portal_keepalive({"job_id": "keepalive"}))

    assert calls == [
        ({"job_id": "keepalive"}, "20260001"),
        ({"job_id": "keepalive"}, "20260002"),
    ]
    assert result == {"refreshed": 1, "needs_reconnect": 1}


def test_keep_portal_session_persists_refreshed_state(monkeypatch):
    import api.sessions as sessions
    import sync.portal_auth as portal_auth

    saved = []
    monkeypatch.setattr(sessions, "load_portal_session", lambda _: {"cookies": ["old"]})
    monkeypatch.setattr(
        portal_auth, "refresh_portal_session", lambda _student_id, _state: {"cookies": ["fresh"]}
    )
    monkeypatch.setattr(sessions, "save_portal_session", lambda student_id, state: saved.append((student_id, state)))

    result = asyncio.run(arq_worker.keep_portal_session({}, "20260001"))

    assert result == {"success": True}
    assert saved == [("20260001", {"cookies": ["fresh"]})]
