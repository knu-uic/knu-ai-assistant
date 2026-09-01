from contextlib import contextmanager


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

    documents.list_notices_for_scan(department="경영학과", grade=2)

    count_query, count_params = connection.calls[0]
    assert "s.department = '공통'" in count_query
    assert "s.department IS NULL" in count_query
    assert "ad.kind = 'department'" in count_query
    assert "NOT EXISTS" in count_query
    assert "ag.kind = 'grade'" in count_query
    assert count_params == ["경영학과", "경영학과", "2학년", "2"]

