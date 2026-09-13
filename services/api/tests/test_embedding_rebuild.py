from api.runtime_settings import load_settings, save_settings
from embedding import rebuild


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

    class Connection:
        rows = [(7, 0, "first", "body", None), (7, 1, "second", "body", None)]

        def execute(self, query, params=()):
            statements.append((" ".join(query.split()), params))
            return self

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return (2,)

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
        "api_key": "",
    }

    rebuild._run_rebuild(target)

    assert load_settings()["embedding"]["model"] == "new-model"
    assert rebuild.rebuild_status()["state"] == "complete"
    assert sum("INSERT INTO notice_chunk" in query for query, _ in statements) == 2
    assert not any(
        "DELETE FROM notice_chunk" in query and params[-1] == 11
        for query, params in statements
    )
