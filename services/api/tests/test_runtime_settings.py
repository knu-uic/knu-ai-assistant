import json

from api.runtime_settings import load_settings, public_settings, save_settings


def test_runtime_settings_roundtrip_and_secret_redaction(tmp_path, monkeypatch):
    path = tmp_path / "manager.json"
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(path))
    saved = save_settings({
        "crawl_enabled": False,
        "crawl_interval_hours": 12,
        "vlm": {"provider": "openai", "model": "gpt-5-mini", "base_url": "", "api_key": "secret"},
    })
    assert load_settings() == saved
    assert saved["crawl_enabled"] is False
    assert public_settings(saved)["vlm"] == {
        "provider": "openai", "model": "gpt-5-mini", "base_url": "", "has_api_key": True,
    }
    assert public_settings(saved)["refine"] == public_settings(saved)["vlm"]
    assert json.loads(path.read_text())["vlm"]["api_key"] == "secret"
    assert path.stat().st_mode & 0o777 == 0o600


def test_school_chat_is_separate_and_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    assert load_settings()["school_chat"]["enabled"] is False
    saved = save_settings({"school_chat": {
        "enabled": True, "provider": "ollama", "model": "school-model",
        "base_url": "http://127.0.0.1:11434/v1",
    }})
    assert saved["school_chat"]["model"] == "school-model"
    assert saved["refine"]["model"] != "school-model"
    changed = save_settings({**saved, "vlm": {"provider": "lmstudio", "model": "image-model"}})
    assert changed["school_chat"] == saved["school_chat"]


def test_school_cloud_key_is_redacted_and_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({"school_chat": {
        "enabled": True, "provider": "google", "model": "gemini-test",
        "base_url": "", "api_key": "school-gemini-key",
    }})
    assert saved["school_chat"]["api_key"] == "school-gemini-key"
    assert public_settings(saved)["school_chat"]["has_api_key"] is True
    assert "api_key" not in public_settings(saved)["school_chat"]
    assert saved["refine"]["api_key"] != "school-gemini-key"


def test_embedding_defaults_to_ollama_and_redacts_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({
        "embedding": {
            "provider": "ollama",
            "model": "bge-m3:latest",
            "base_url": "http://127.0.0.1:11434/v1",
            "dimension": 1024,
            "api_key": "embedding-secret",
        },
    })

    assert saved["embedding"]["provider"] == "ollama"
    assert saved["embedding"]["chunk_size"] == 280
    assert saved["embedding"]["chunk_overlap"] == 80
    assert public_settings(saved)["embedding"]["has_api_key"] is True
    assert "api_key" not in public_settings(saved)["embedding"]


def test_reranker_defaults_to_local_bge_and_survives_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))

    saved = save_settings({
        "reranker": {
            "enabled": True,
            "provider": "local",
            "model": "BAAI/bge-reranker-v2-m3",
            "max_length": 512,
        },
    })

    assert load_settings() == saved
    assert saved["reranker"] == {
        "enabled": True,
        "provider": "local",
        "model": "BAAI/bge-reranker-v2-m3",
        "max_length": 512,
    }


def test_embedding_chunk_settings_are_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({
        "embedding": {"chunk_size": 120, "chunk_overlap": 999},
    })

    assert saved["embedding"]["chunk_size"] == 120
    assert saved["embedding"]["chunk_overlap"] == 119


def test_runtime_settings_rejects_unknown_values(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({"crawl_interval_hours": 5, "vlm": {"provider": "unknown"}})
    assert saved["crawl_enabled"] is False
    assert saved["crawl_interval_hours"] == 6
    assert saved["vlm"]["provider"] in {"lmstudio", "ollama", "openai", "google", "openai-codex"}


def test_runtime_settings_accepts_codex_oauth(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({
        "crawl_interval_hours": 6,
        "vlm": {"provider": "openai-codex", "model": "gpt-5.6-sol", "base_url": "", "api_key": ""},
    })
    assert saved["vlm"]["provider"] == "openai-codex"
    assert saved["vlm"]["model"] == "gpt-5.6-sol"
    assert saved["refine"]["provider"] != "openai-codex"


def test_refine_model_remains_independent_after_image_model_change(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    original = save_settings({
        "vlm": {"provider": "lmstudio", "model": "image-model", "base_url": "http://localhost:1234/v1"},
        "refine": {"provider": "ollama", "model": "notice-model", "base_url": "http://localhost:11434/v1"},
    })
    changed = save_settings({**original, "vlm": {"provider": "google", "model": "image-only"}})
    assert changed["refine"] == original["refine"]
    assert changed["vlm"]["model"] == "image-only"


def test_codex_is_valid_for_refine_when_explicitly_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({"refine": {"provider": "openai-codex", "model": "gpt-5.6-sol"}})
    assert saved["refine"]["provider"] == "openai-codex"
    assert saved["refine"]["model"] == "gpt-5.6-sol"


def test_crawl_mode_and_scope_survive_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_MANAGER_SETTINGS_PATH", str(tmp_path / "manager.json"))
    saved = save_settings({
        "crawl_enabled": False,
        "crawl_interval_hours": 12,
        "crawl_request": {
            "mode": "range",
            "start_page": 2,
            "end_page": 6,
            "recent_days": 7,
            "refresh_outdated_extraction": True,
            "source_codes": ["cse_notice", "main_notice"],
        },
    })

    assert load_settings() == saved
    assert load_settings()["crawl_request"] == {
        "mode": "range",
        "start_page": 2,
        "end_page": 6,
        "recent_days": 7,
        "refresh_outdated_extraction": True,
        "source_codes": ["cse_notice", "main_notice"],
    }
