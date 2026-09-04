import asyncio

from workers.arq_worker import WorkerSettings, poll_notices, scheduled_poll_notices
from workers import arq_worker


def test_worker_has_notice_polling_cron():
    jobs = WorkerSettings.cron_jobs
    assert len(jobs) == 1
    job = jobs[0]
    assert job.coroutine is scheduled_poll_notices
    # 이전 실행 미종료 시 중복 발화 방지
    assert job.unique is True
    # 매시 정각에 runtime setting(1/6/12/24시간)을 확인한다.
    assert job.minute == {0}


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
