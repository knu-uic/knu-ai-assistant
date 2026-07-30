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
