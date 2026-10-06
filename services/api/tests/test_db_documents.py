from contextlib import contextmanager
from datetime import date


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((str(query), list(params)))
        return _Result(0 if len(self.calls) == 1 else None)


class _Pool:
    def __init__(self, connection):
        self._connection = connection

    @contextmanager
    def connection(self):
        yield self._connection


def test_notice_scope_keeps_general_notices_for_explicit_department_and_grade(
    monkeypatch,
):
    """A requested audience narrows targeted notices but must retain general notices."""
    from db import documents

    connection = _Connection()
    monkeypatch.setattr(documents, "sync_pool", _Pool(connection))

    documents.list_content_for_scan(department="경영학과", grade=2)

    count_query, count_params = connection.calls[0]
    assert "s.department = '공통'" in count_query
    assert "s.department IS NULL" in count_query
    assert "ad.kind = 'department'" in count_query
    assert "NOT EXISTS" in count_query
    assert "ag.kind = 'grade'" in count_query
    assert count_params == ["경영학과", "경영학과", "2학년", "2"]


def test_content_scan_uses_normalized_content_type(monkeypatch):
    from db import documents

    connection = _Connection()
    monkeypatch.setattr(documents, "sync_pool", _Pool(connection))

    documents.list_content_for_scan(content_type="academic")

    count_query, count_params = connection.calls[0]
    assert "n.content_type = %s" in count_query
    assert "s.kind = %s" not in count_query
    assert count_params == ["academic"]


def test_application_url_lookup_only_returns_valid_web_links(monkeypatch):
    from db import documents

    class Result:
        def fetchall(self):
            return [
                ("notice-1", "https://forms.gle/example"),
                ("notice-2", "javascript:alert(1)"),
                ("notice-3", "https://bad.test/with space"),
                ("notice-4", None),
            ]

    class Connection:
        def execute(self, query, params):
            assert "n.content_type = 'notice'" in str(query)
            assert set(params[0]) == {"notice-1", "notice-2", "notice-3", "notice-4"}
            return Result()

    monkeypatch.setattr(documents, "sync_pool", _Pool(Connection()))
    assert documents.get_notice_application_urls(
        ["notice-1", "notice-2", "notice-3", "notice-4"]
    ) == {"notice-1": "https://forms.gle/example"}


def test_outdated_completed_url_is_refreshed_only_when_requested(monkeypatch):
    from db import documents

    url = "https://example.test/bbs/X/1/artclView.do"
    posted_at = date.today()

    class Result:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((str(query), params))
            if "SELECT url, status, extraction_version" in str(query):
                return Result([(url, "completed", "notice-v4", posted_at)])
            return Result()

        def commit(self):
            return None

    record = {"url": url, "posted_at": posted_at.isoformat(), "is_pinned": False}

    connection = Connection()
    monkeypatch.setattr(documents, "sync_pool", _Pool(connection))
    assert documents.select_crawl_records(
        1, [record], refresh_outdated_extraction=False
    ) == []

    connection = Connection()
    monkeypatch.setattr(documents, "sync_pool", _Pool(connection))
    assert documents.select_crawl_records(
        1, [record], refresh_outdated_extraction=True
    ) == [record]
