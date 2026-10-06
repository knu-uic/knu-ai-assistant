from api.runtime_settings import load_settings, save_settings
from embedding import rebuild


def test_incomplete_ready_dataset_is_rebuilt(monkeypatch):
    target = {
        "provider": "ollama",
        "model": "bge-m3:latest",
        "base_url": "http://127.0.0.1:11434/v1",
        "dimension": 1024,
        "api_key": "",
    }
    existing = {
        "id": 8,
        "status": "ready",
        "completed_notices": 0,
        "total_notices": 0,
        "total_chunks": 0,
        "completed_at": None,
    }
    started = []

    class ImmediateThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            started.append(self.args)

    rebuild._set_status(state="idle", completed=0, total=0, target=None)
    monkeypatch.setattr(rebuild, "find_dataset", lambda _target: existing)
    monkeypatch.setattr(rebuild, "active_dataset_id", lambda: 2)
    monkeypatch.setattr(rebuild, "_set_dataset", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rebuild, "Thread", ImmediateThread)
    monkeypatch.setattr(
        rebuild, "activate_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not reuse")),
    )

    result = rebuild.start_rebuild(target)

    assert result["state"] == "running"
    assert result["reused"] is False
    assert started == [(target, 8)]


def test_rebuild_keeps_old_rows_until_target_is_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    save_settings({
        "embedding": {
            "provider": "ollama",
            "model": "old-model",
            "base_url": "http://127.0.0.1:11434/v1",
            "dimension": 3,
            "api_key": "",
        },
    })
    statements = []

    class Result:
        def __init__(self, *, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.row

    class Connection:
        def execute(self, query, params=()):
            normalized = " ".join(query.split())
            statements.append((normalized, params))
            if "pg_try_advisory_lock" in normalized:
                return Result(row=(True,))
            if "SELECT content_id, title" in normalized:
                return Result(rows=[(7, "공지", "x" * 400)])
            if "FROM content_asset" in normalized:
                return Result(rows=[])
            if "SELECT count(*) FROM content_chunk" in normalized:
                return Result(row=(2,))
            return Result()

        def commit(self):
            return None

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return Context()

    class Embedder:
        def embed_documents(self, texts):
            return [[float(index), 0.0, 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setattr(rebuild, "sync_pool", Pool())
    monkeypatch.setattr(rebuild, "get_embeddings", lambda _settings: Embedder())
    monkeypatch.setattr(rebuild, "ensure_dataset", lambda *_args, **_kwargs: 22)
    monkeypatch.setattr(rebuild, "active_dataset_id", lambda: 11)
    monkeypatch.setattr(rebuild, "_set_dataset", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rebuild, "ensure_search_index", lambda *_args: "hnsw")

    def activate(_dataset_id, *, api_key=""):
        settings = load_settings()
        settings["embedding"] = target
        save_settings(settings)

    monkeypatch.setattr(rebuild, "activate_dataset", activate)
    target = {
        "provider": "ollama",
        "model": "new-model",
        "base_url": "http://127.0.0.1:11434/v1",
        "dimension": 3,
        "chunk_size": 280,
        "chunk_overlap": 80,
        "api_key": "",
    }

    rebuild._run_rebuild(target)

    assert load_settings()["embedding"]["model"] == "new-model"
    assert rebuild.rebuild_status()["state"] == "complete"
    assert sum("INSERT INTO content_chunk" in query for query, _ in statements) == 2
    assert not any(
        "DELETE FROM content_chunk" in query and params[-1] == 11
        for query, params in statements
    )
