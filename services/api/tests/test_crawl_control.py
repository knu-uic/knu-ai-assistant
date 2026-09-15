from workers import crawl_control


def test_cleanup_interrupted_crawl_only_removes_transient_job_state(monkeypatch):
    calls = []

    class Redis:
        def get(self, key):
            if key == "notice-crawl:active":
                return b"manual-notice-crawl-live"
            if key == "notice-crawl:pending":
                return b"manual-notice-crawl-pending"
            return None

        def delete(self, *keys):
            calls.append(("delete", keys))
            return len(keys)

        def zrem(self, key, *values):
            calls.append(("zrem", key, values))
            return len(values)

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr("redis.from_url", lambda _url: Redis())

    assert crawl_control.cleanup_interrupted_crawl() == 20
    deleted = calls[0][1]
    assert "notice-crawl:active" in deleted
    assert "arq:job:manual-notice-crawl-live" in deleted
    assert "arq:job:manual-notice-crawl-pending" in deleted
    assert all("document" not in key and "notice:" not in key for key in deleted)
    assert calls[1][0:2] == ("zrem", "arq:queue")
    assert set(calls[1][2]) == {
        "manual-notice-crawl",
        "manual-notice-crawl-live",
        "manual-notice-crawl-pending",
    }
