import asyncio

import httpx
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
    assert {item["code"] for item in response.json()["capabilities"]["crawl_sources"]} >= {
        "main_notice", "cse_notice", "business_notice"
    }
    main_notice = next(
        item for item in response.json()["capabilities"]["crawl_sources"]
        if item["code"] == "main_notice"
    )
    assert main_notice["name"] == "공주대학교 학생 공지"


def test_admin_tool_catalog_comes_from_live_mcp_registry():
    with TestClient(app) as client:
        response = client.get("/api/admin/tools")

    assert response.status_code == 200
    result = response.json()
    assert result["count"] == len(result["items"])
    by_name = {item["name"]: item for item in result["items"]}
    assert "knu_search_notice_details" in by_name
    assert by_name["knu_search_notice_details"]["group"] == "knu.notices"
    assert by_name["knu_search_notice_details"]["annotations"]["readOnlyHint"] is True
    assert "query" in by_name["knu_search_notice_details"]["input_schema"]["properties"]


def test_manual_crawl_forwards_url_based_page_scope(monkeypatch):
    captured = {}

    class Job:
        job_id = "manual-notice-crawl"

    class Redis:
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
        async def execute(self, _query):
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
            assert key == "notice-crawl:active"
            return 1

    async def get_pool():
        return Redis()

    monkeypatch.setattr(admin, "pool", Pool())
    monkeypatch.setattr(admin, "get_arq_pool", get_pool)

    result = asyncio.run(admin.crawl_status())

    assert result == {
        "active": True,
        "total": 25,
        "completed": 20,
        "discovered": 3,
        "failed": 2,
        "last_seen_at": None,
    }


def test_admin_updates_runtime_settings_without_returning_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_ADMIN_TOKEN", "manager-secret")
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
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


def test_notice_filter_catalog(monkeypatch):
    results = iter([
        [("main_notice", "공주대학교 학생 공지"), ("cse_notice", "컴퓨터공학과 공지")],
        [(2026,), (2025,)],
        [("notice-v5",), ("notice-v4",)],
    ])

    class Result:
        async def fetchall(self):
            return next(results)

    class Connection:
        async def execute(self, _query):
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
            ]})

    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = asyncio.run(admin._discover_vlm_models(admin.VlmSettings(
        provider="ollama", model="", base_url="http://127.0.0.1:11434/v1"
    )))
    assert requested == ["http://127.0.0.1:11434/api/tags"]
    assert result["models"] == ["gemma3:4b", "qwen3-vl:8b"]


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
        [(7, "title", "수강", None, None, 0.9, None, "source", "https://example.com", "notice-v5", 1000, ["asset"])],
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
    assert result["items"][0]["asset_file_bytes"] == 300
    assert result["items"][0]["storage_bytes"] == 1300
