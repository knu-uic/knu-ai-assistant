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
    assert json.loads(path.read_text())["vlm"]["api_key"] == "secret"
    assert path.stat().st_mode & 0o777 == 0o600


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
