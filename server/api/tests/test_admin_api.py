import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from interfaces.http import admin


def test_admin_settings_requires_configured_token(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    with TestClient(app) as client:
        assert client.get("/api/admin/settings").status_code == 401
        response = client.get(
            "/api/admin/settings",
            headers={"Authorization": "Bearer manager-secret"},
        )
    assert response.status_code == 200
    assert response.json()["capabilities"]["crawl_intervals"] == [1, 6, 12, 24]
    assert response.json()["capabilities"]["crawl_modes"] == ["all", "recent", "range"]
    assert response.json()["capabilities"]["current_extraction_version"] == "notice-v5"
    assert response.json()["reranker"]["provider"] == "local"
    assert response.json()["capabilities"]["reranker_models"] == [
        "BAAI/bge-reranker-v2-m3"
    ]
    assert {item["code"] for item in response.json()["capabilities"]["crawl_sources"]} >= {
        "main_notice", "cse_notice", "software_notice", "business_notice",
        "software_curriculum",
    }
    main_notice = next(
        item for item in response.json()["capabilities"]["crawl_sources"]
        if item["code"] == "main_notice"
    )
    assert main_notice["name"] == "공주대학교 학생 공지"


def test_admin_reranker_status_uses_runtime_model_state(monkeypatch):
    monkeypatch.setattr(
        admin,
        "reranker_status",
        lambda: {
            "enabled": True,
            "provider": "local",
            "model": "BAAI/bge-reranker-v2-m3",
            "installed": False,
            "bytes": 0,
            "effective_status": "vector_fallback",
            "download": {"state": "idle", "model": None, "error": None},
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/admin/settings/reranker")

    assert response.status_code == 200
    assert response.json()["effective_status"] == "vector_fallback"


def test_admin_tool_catalog_comes_from_live_mcp_registry():
    with TestClient(app) as client:
        response = client.get("/api/admin/tools")

    assert response.status_code == 200
    result = response.json()
    assert result["count"] == len(result["items"])
    by_name = {item["name"]: item for item in result["items"]}
    assert "knu_search_notice_details" in by_name
    assert by_name["knu_search_notice_details"]["group"] == "knu.notice"
    assert by_name["knu_search_academic_details"]["group"] == "knu.academic"
    assert by_name["knu_search_notice_details"]["annotations"]["readOnlyHint"] is True
    assert "query" in by_name["knu_search_notice_details"]["input_schema"]["properties"]


def test_admin_account_portal_data_is_scoped_and_excludes_credentials(monkeypatch):
    seen = []

    class Result:
        def __init__(self, rows):
            self.rows = rows

        async def fetchone(self):
            return self.rows[0] if self.rows else None

        async def fetchall(self):
            return self.rows

    class Connection:
        async def execute(self, query, params):
            seen.append((query, params))
            if "FROM users" in query:
                return Result([("20260001", "학생", "컴퓨터공학", 2, "AI, 보안", "자료구조",
                                {"earned": 30}, [{"course": "자료구조"}], {"A": 3}, {"gpa": 4.0})])
            if "FROM lms_courses" in query:
                return Result([(123, "자료구조", None)])
            return Result([("assignment", "과제", "자료구조", None, 50, None, False, "canvas", None)])

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    monkeypatch.setattr(admin, "pool", Pool())
    result = asyncio.run(admin.account_portal_data("20260001"))
    assert result["timetable"] == [{"course": "자료구조"}]
    assert result["graduation_credits"] == {"earned": 30}
    assert result["lms_courses"][0]["course_name"] == "자료구조"
    assert result["lms_tasks"][0]["title"] == "과제"
    assert result["interests"] == ["AI", "보안"]
    assert all(params == ("20260001",) for _, params in seen)
    assert not {"password", "token", "session", "raw"} & result.keys()


def test_admin_account_portal_data_requires_admin_token(monkeypatch):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    with TestClient(app) as client:
        response = client.get("/api/admin/accounts/20260001/portal-data")
    assert response.status_code == 401


def test_database_schema_reports_content_model_and_physical_keys(monkeypatch):
    queries = {
        "information_schema.columns": [
            ("content", "content_id", "bigint", "int8", "NO", "nextval('notice_id_seq')", 1),
            ("content", "source_id", "bigint", "int8", "NO", None, 2),
            ("source", "source_id", "bigint", "int8", "NO", "nextval('source_id_seq')", 1),
            ("source", "kind", "character varying", "varchar", "NO", None, 2),
        ],
        "information_schema.table_constraints": [
            ("content", "content_id", "PRIMARY KEY", "content", "content_id", None),
            ("content", "source_id", "FOREIGN KEY", "source", "source_id", "CASCADE"),
            ("source", "source_id", "PRIMARY KEY", "source", "source_id", None),
        ],
        "pg_stat_user_tables": [("content", 42), ("source", 5)],
        "schema_migrations": [("001_baseline.sql", None), ("012_content_model.sql", None)],
    }

    class Result:
        def __init__(self, rows):
            self.rows = rows

        async def fetchall(self):
            return self.rows

    class Connection:
        async def execute(self, query, _params=None):
            key = next(name for name in queries if name in query)
            return Result(queries[key])

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    monkeypatch.setattr(admin, "pool", Pool())
    result = asyncio.run(admin.database_schema())

    tables = {table["name"]: table for table in result["tables"]}
    content_columns = {column["name"]: column for column in tables["content"]["columns"]}
    assert result["model"] == "content-v3"
    assert "content" in result["storage_rule"]
    assert result["latest_migration"] == "012_content_model.sql"
    assert tables["content"]["row_count"] == 42
    assert content_columns["content_id"]["kind"] == "pk"
    assert content_columns["source_id"]["kind"] == "fk"
    assert content_columns["source_id"]["references"] == "source.source_id"


def test_manual_crawl_forwards_url_based_page_scope(monkeypatch):
    captured = {}

    class Job:
        job_id = "manual-notice-crawl"

    class Redis:
        async def exists(self, _key):
            return 0

        async def set(self, key, value, **_kwargs):
            captured["pending"] = (key, value)
            return True

        async def delete(self, *_keys):
            pass

        async def enqueue_job(self, function, request, **kwargs):
            captured.update(function=function, request=request, kwargs=kwargs)
            return Job()

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/crawl/run",
            json={
                "mode": "range",
                "start_page": 3,
                "end_page": 20,
                "refresh_outdated_extraction": True,
                "source_codes": ["cse_notice"],
            },
        )

    assert response.status_code == 200
    assert captured["function"] == "poll_notices"
    assert captured["kwargs"]["_job_id"].startswith("manual-notice-crawl-")
    assert captured["pending"] == (
        "notice-crawl:pending", captured["kwargs"]["_job_id"],
    )
    assert captured["request"]["start_page"] == 3
    assert captured["request"]["end_page"] == 20
    assert captured["request"]["refresh_outdated_extraction"] is True
    assert captured["request"]["source_codes"] == ["cse_notice"]


def test_manual_crawl_rejects_invalid_range():
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/crawl/run",
            json={"mode": "range", "start_page": 20, "end_page": 3},
        )
    assert response.status_code == 422


def test_manual_crawl_is_blocked_while_automatic_collection_is_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    admin.save_settings({"crawl_enabled": True, "crawl_interval_hours": 6})
    with TestClient(app) as client:
        response = client.post("/api/admin/crawl/run", json={"mode": "all"})

    assert response.status_code == 409
    assert "자동 수집" in response.json()["detail"]


def test_crawl_status_reports_url_registry_counts(monkeypatch):
    class Result:
        async def fetchone(self):
            return (25, 20, 3, 2, None)

    class Connection:
        async def execute(self, _query, _params=None):
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    class Redis:
        async def exists(self, key):
            return int(key == "notice-crawl:active")

        async def get(self, key):
            assert key == "notice-crawl:progress"
            return b'{"status":"running","processed":7,"saved":5}'

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "pool", Pool())
    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    monkeypatch.setattr(
        admin,
        "load_crawl_progress",
        lambda: {"status": "running", "processed": 7, "saved": 5},
    )

    result = asyncio.run(admin.crawl_status())

    assert result == {
        "active": True,
        "pending": False,
        "paused": False,
        "stop_requested": False,
        "total": 25,
        "completed": 20,
        "discovered": 3,
        "failed": 2,
        "last_seen_at": None,
        "run": {"status": "running", "processed": 7, "saved": 5},
    }


def test_notice_list_sync_runs_all_sources_when_idle(monkeypatch):
    expected = {
        "ok": True,
        "sources": [{"code": "main_notice", "status": "complete"}],
        "pages": 12,
        "notices": 234,
        "new": 10,
        "duration_ms": 3210,
    }

    class Redis:
        async def exists(self, _key):
            return 0

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    monkeypatch.setattr(admin, "sync_notice_lists", lambda: expected)
    with TestClient(app) as client:
        response = client.post("/api/admin/notices/sync-list")

    assert response.status_code == 200
    assert response.json() == expected


def test_notice_list_sync_is_blocked_during_collection(monkeypatch):
    class Redis:
        async def exists(self, key):
            return int(key == "notice-crawl:active")

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    with TestClient(app) as client:
        response = client.post("/api/admin/notices/sync-list")

    assert response.status_code == 409
    assert "수집 중" in response.json()["detail"]


def test_crawl_pause_resume_and_stop_controls(monkeypatch):
    class Redis:
        def __init__(self):
            self.values = {"notice-crawl:active": "manual-notice-crawl"}

        async def exists(self, key):
            return int(key in self.values)

        async def set(self, key, value, **_kwargs):
            self.values[key] = value
            return True

        async def delete(self, *keys):
            for key in keys:
                self.values.pop(key, None)

    redis = Redis()

    async def get_pool():
        return redis

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    with TestClient(app) as client:
        assert client.post("/api/admin/crawl/pause").json() == {
            "ok": True, "state": "pausing",
        }
        assert "notice-crawl:pause" in redis.values
        assert client.post("/api/admin/crawl/resume").json() == {
            "ok": True, "state": "running",
        }
        assert "notice-crawl:pause" not in redis.values
        assert client.post("/api/admin/crawl/stop").json() == {
            "ok": True, "state": "stopping",
        }
        assert "notice-crawl:stop" in redis.values


def test_crawl_controls_require_an_active_run(monkeypatch):
    class Redis:
        async def exists(self, _key):
            return 0

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    with TestClient(app) as client:
        response = client.post("/api/admin/crawl/pause")

    assert response.status_code == 409
    assert "실행 중" in response.json()["detail"]


def test_dismiss_crawl_closes_only_visible_run(monkeypatch):
    deleted = []
    saved = []

    class Redis:
        async def exists(self, _key):
            return 0

        async def delete(self, *keys):
            deleted.extend(keys)

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)
    monkeypatch.setattr(admin, "load_crawl_progress", lambda: {"status": "stopped"})
    monkeypatch.setattr(admin, "save_crawl_progress", lambda value: saved.append(value))

    result = asyncio.run(admin.dismiss_crawl())

    assert result["state"] == "dismissed"
    assert result["preserved_notice_list"] is True
    assert result["preserved_checkpoints"] is True
    assert result["preserved_assets"] is True
    assert saved[0]["status"] == "dismissed"
    assert saved[0]["resumable"] is False
    assert "notice-crawl:progress" in deleted


def test_dismiss_crawl_rejects_active_run(monkeypatch):
    class Redis:
        async def exists(self, key):
            return int(key == "notice-crawl:active")

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "get_arq_pool", get_pool)

    with pytest.raises(admin.HTTPException) as error:
        asyncio.run(admin.dismiss_crawl())

    assert error.value.status_code == 409


@pytest.mark.parametrize("refine_model", ["", "test-refine-model"])
def test_admin_updates_runtime_settings_without_returning_secret(tmp_path, monkeypatch, refine_model):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    monkeypatch.setenv("LLM_MODEL", refine_model)
    with TestClient(app) as client:
        response = client.put(
            "/api/admin/settings",
            headers={"Authorization": "Bearer manager-secret"},
            json={
                "crawl_enabled": False,
                "crawl_interval_hours": 12,
                "vlm": {
                    "provider": "openai",
                    "model": "gpt-5-mini",
                    "base_url": "",
                    "api_key": "do-not-return",
                },
            },
        )
    assert response.status_code == 200
    assert response.json()["crawl_enabled"] is False
    assert response.json()["crawl_interval_hours"] == 12
    assert response.json()["vlm"]["has_api_key"] is True
    assert "api_key" not in response.json()["vlm"]
    assert response.json()["refine"]["model"] == refine_model
    assert "api_key" not in response.json()["refine"]


def test_admin_saves_refine_model_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    with TestClient(app) as client:
        response = client.put(
            "/api/admin/settings",
            headers={"Authorization": "Bearer manager-secret"},
            json={
                "crawl_interval_hours": 6,
                "vlm": {"provider": "lmstudio", "model": "image-model"},
                "refine": {"provider": "ollama", "model": "notice-model", "base_url": "http://localhost:11434/v1"},
            },
        )
    assert response.status_code == 200
    assert response.json()["vlm"]["model"] == "image-model"
    assert response.json()["refine"]["model"] == "notice-model"


def test_admin_imports_environment_api_key_without_returning_secret(tmp_path, monkeypatch):
    from api.runtime_settings import load_settings

    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-secret")
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/settings/import-api-key",
            headers={"Authorization": "Bearer manager-secret"},
            json={"purpose": "refine", "provider": "openai", "model": "gpt-test"},
        )
    assert response.status_code == 200
    assert response.json()["refine"]["has_api_key"] is True
    assert "test-openai-secret" not in response.text
    assert load_settings()["refine"]["api_key"] == "test-openai-secret"


def test_admin_reports_missing_gemini_environment_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/settings/import-api-key",
            headers={"Authorization": "Bearer manager-secret"},
            json={"purpose": "refine", "provider": "google", "model": "gemini-test"},
        )
    assert response.status_code == 404


def test_notice_filter_catalog(monkeypatch):
    results = iter([
        [("main_notice", "공주대학교 학생 공지"), ("cse_notice", "컴퓨터공학과 공지")],
        [(2026,), (2025,)],
        [("notice-v5",), ("notice-v4",)],
        [("ollama · bge-m3:latest",)],
    ])

    class Result:
        async def fetchall(self):
            return next(results)

    class Connection:
        async def execute(self, _query, _params=None):
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    monkeypatch.setattr(admin, "pool", Pool())
    result = asyncio.run(admin.notice_filters())

    assert result["sources"][1] == {"code": "cse_notice", "name": "컴퓨터공학과 공지"}
    assert result["years"] == [2026, 2025]
    assert result["extraction_versions"] == ["notice-v5", "notice-v4"]
    assert result["embedding_models"] == ["ollama · bge-m3:latest"]
    assert "일반(기타)" in result["categories"]


def test_lmstudio_models_use_native_catalog_and_filter_embeddings(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    requested = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            requested.append(url)
            return httpx.Response(200, request=httpx.Request("GET", url), json={"models": [
                {"key": "qwen/qwen3-vl", "type": "vlm"},
                {"key": "text-embedding-nomic", "type": "embedding"},
            ]})

    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(admin._discover_vlm_models(admin.VlmSettings(
        provider="lmstudio", model="", base_url="http://127.0.0.1:1234/v1"
    )))
    assert requested == ["http://127.0.0.1:1234/api/v1/models"]
    assert result["models"] == ["qwen/qwen3-vl"]


def test_ollama_models_use_installed_model_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    requested = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            requested.append(url)
            return httpx.Response(200, request=httpx.Request("GET", url), json={"models": [
                {"model": "gemma3:4b"}, {"name": "qwen3-vl:8b", "capabilities": ["vision", "completion"]},
                {"name": "bge-m3", "capabilities": ["embedding"]},
                {"name": "qwen3-embedding", "capabilities": ["tools", "embedding"]},
            ]})

        async def post(self, url, json):
            requested.append(url)
            assert json == {"model": "gemma3:4b"}
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "capabilities": ["completion", "tools"],
            })

    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(admin._discover_vlm_models(admin.VlmSettings(
        provider="ollama", model="", base_url="http://127.0.0.1:11434/v1"
    )))
    assert requested == ["http://127.0.0.1:11434/api/tags", "http://127.0.0.1:11434/api/show"]
    assert result["models"] == ["gemma3:4b", "qwen3-vl:8b"]


def test_school_cloud_setting_accepts_api_provider_but_rejects_remote_local_url():
    admin._validate_school_chat(admin.SchoolChatSettings(
        enabled=True, provider="google", model="gemini-test", base_url="",
    ))
    with pytest.raises(HTTPException) as error:
        admin._validate_school_chat(admin.SchoolChatSettings(
            enabled=True, provider="ollama", model="qwen", base_url="https://external.example/v1",
        ))
    assert error.value.status_code == 422


def test_ollama_embedding_models_only_include_embedding_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            return httpx.Response(200, request=httpx.Request("GET", url), json={"models": [
                {"model": "gemma4:12b-mlx", "capabilities": ["completion", "vision"]},
                {"model": "bge-m3:latest", "capabilities": ["embedding"]},
            ]})

    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(admin._discover_embedding_models(admin.EmbeddingSettings(
        provider="ollama", base_url="http://127.0.0.1:11434/v1"
    )))
    assert result["models"] == ["bge-m3:latest"]


def test_ollama_embedding_model_info_reads_native_dimension(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    requested = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            requested.append((url, kwargs["json"]))
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "details": {"parameter_size": "7.6B"},
                "model_info": {
                    "qwen3.context_length": 40960,
                    "qwen3.embedding_length": 4096,
                },
            })

    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(admin._discover_embedding_model_info(admin.EmbeddingSettings(
        provider="ollama", model="qwen3-embedding:latest",
        base_url="http://127.0.0.1:11434/v1",
    )))

    assert requested == [("http://127.0.0.1:11434/api/show", {"model": "qwen3-embedding:latest"})]
    assert result["native_dimension"] == 4096
    assert result["parameter_size"] == "7.6B"


def test_notice_storage_combines_database_and_unique_asset_files(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"a" * 120)
    second.write_bytes(b"b" * 80)
    results = iter([(3, 1500), (5, ["first", "first", "second"])])

    class Result:
        async def fetchone(self):
            return next(results)

    class Connection:
        async def execute(self, *_args):
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    files = {"first": first, "second": second}
    monkeypatch.setattr(admin, "pool", Pool())
    monkeypatch.setattr(admin, "resolve_asset_path", lambda value: files[value])

    result = asyncio.run(admin.notice_storage())

    assert result == {
        "bytes": 1700,
        "database_bytes": 1500,
        "asset_file_bytes": 200,
        "notice_count": 3,
        "asset_count": 5,
    }


def test_notice_list_reports_each_notice_storage_size(tmp_path, monkeypatch):
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"x" * 300)
    results = iter([
        (1,),
        [(7, "title", "수강", None, None, None, "source", "https://example.com", "notice-v5", ["ollama · bge-m3:latest"], 1000, ["asset"])],
    ])

    class Result:
        async def fetchone(self):
            return next(results)

        async def fetchall(self):
            return next(results)

    class Connection:
        async def execute(self, *_args):
            return Result()

    class ConnectionContext:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def connection(self):
            return ConnectionContext()

    monkeypatch.setattr(admin, "pool", Pool())
    monkeypatch.setattr(admin, "resolve_asset_path", lambda _value: asset)

    result = asyncio.run(admin.list_notices())

    assert result["total"] == 1
    assert result["items"][0]["database_bytes"] == 1000
    assert result["items"][0]["embedding_models"] == ["ollama · bge-m3:latest"]
    assert result["items"][0]["asset_file_bytes"] == 300
    assert result["items"][0]["storage_bytes"] == 1300
