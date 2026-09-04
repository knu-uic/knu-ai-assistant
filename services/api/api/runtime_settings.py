"""Server Manager가 공유하는 런타임 설정 저장소.

API와 ARQ worker가 같은 JSON 파일을 읽는다. API key가 들어갈 수 있으므로
파일 권한은 소유자만 읽고 쓸 수 있는 0600으로 유지한다.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

ALLOWED_CRAWL_INTERVAL_HOURS = (1, 6, 12, 24)
ALLOWED_VLM_PROVIDERS = ("ollama", "lmstudio", "openai", "google", "openai-codex")

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "server-manager.json"
_LOCK = RLock()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


def settings_path() -> Path:
    return Path(os.getenv("KNU_MANAGER_SETTINGS_PATH", str(_DEFAULT_PATH))).expanduser()


def default_settings() -> dict:
    provider = (os.getenv("VLM_PROVIDER") or "local").strip().lower()
    provider = {"local": "lmstudio", "openai-api": "openai", "gemini": "google"}.get(provider, provider)
    if provider not in ALLOWED_VLM_PROVIDERS:
        provider = "lmstudio"
    key = ""
    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY") or ""
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    return {
        # 첫 설치나 사용자가 명시적으로 켜지지 안도록 기본은 OFF로 둔다.
        "crawl_enabled": _env_bool("NOTICE_POLL_ENABLED", False),
        "crawl_interval_hours": int(os.getenv("NOTICE_POLL_HOURS", "6")),
        "crawl_request": {
            "mode": "all",
            "start_page": 1,
            "end_page": None,
            "recent_days": 7,
            "refresh_outdated_extraction": False,
            "source_codes": [],
        },
        "vlm": {
            "provider": provider,
            "model": os.getenv("LLM_MODEL") or "",
            "base_url": os.getenv("OPENAI_COMPAT_BASE_URL") or "http://127.0.0.1:1234/v1",
            "api_key": key,
        },
    }


def _sanitize(raw: dict) -> dict:
    defaults = default_settings()
    try:
        interval = int(raw.get("crawl_interval_hours", defaults["crawl_interval_hours"]))
    except (TypeError, ValueError):
        interval = defaults["crawl_interval_hours"]
    if interval not in ALLOWED_CRAWL_INTERVAL_HOURS:
        interval = 6
    enabled_raw = raw.get("crawl_enabled", defaults["crawl_enabled"])
    crawl_enabled = (
        enabled_raw.strip().lower() not in {"0", "false", "off", "no"}
        if isinstance(enabled_raw, str)
        else bool(enabled_raw)
    )

    request_raw = raw.get("crawl_request") if isinstance(raw.get("crawl_request"), dict) else {}
    mode = str(request_raw.get("mode", defaults["crawl_request"]["mode"]))
    if mode not in {"all", "recent", "range"}:
        mode = "all"
    try:
        start_page = max(1, int(request_raw.get("start_page", 1)))
    except (TypeError, ValueError):
        start_page = 1
    try:
        end_value = request_raw.get("end_page")
        end_page = max(start_page, int(end_value)) if end_value is not None else None
    except (TypeError, ValueError):
        end_page = None
    if mode == "range" and end_page is None:
        end_page = start_page
    try:
        recent_days = min(90, max(1, int(request_raw.get("recent_days", 7))))
    except (TypeError, ValueError):
        recent_days = 7
    source_codes = request_raw.get("source_codes", [])
    if not isinstance(source_codes, list):
        source_codes = []
    source_codes = list(dict.fromkeys(
        str(value).strip() for value in source_codes if str(value).strip()
    ))

    vlm_raw = raw.get("vlm") if isinstance(raw.get("vlm"), dict) else {}
    provider = str(vlm_raw.get("provider", defaults["vlm"]["provider"])).strip().lower()
    if provider not in ALLOWED_VLM_PROVIDERS:
        provider = defaults["vlm"]["provider"]
    base_url = str(vlm_raw.get("base_url", defaults["vlm"]["base_url"])).strip()
    return {
        "crawl_enabled": crawl_enabled,
        "crawl_interval_hours": interval,
        "crawl_request": {
            "mode": mode,
            "start_page": start_page,
            "end_page": end_page,
            "recent_days": recent_days,
            "refresh_outdated_extraction": bool(request_raw.get("refresh_outdated_extraction", False)),
            "source_codes": source_codes,
        },
        "vlm": {
            "provider": provider,
            "model": str(vlm_raw.get("model", defaults["vlm"]["model"])).strip(),
            "base_url": base_url,
            "api_key": str(vlm_raw.get("api_key", defaults["vlm"]["api_key"])),
        },
    }


def load_settings() -> dict:
    path = settings_path()
    with _LOCK:
        if not path.exists():
            return _sanitize({})
        try:
            return _sanitize(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return _sanitize({})


def save_settings(raw: dict) -> dict:
    value = _sanitize(raw)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return value


def public_settings(value: dict | None = None) -> dict:
    result = load_settings() if value is None else value
    safe = json.loads(json.dumps(result))
    key = safe["vlm"].pop("api_key", "")
    safe["vlm"]["has_api_key"] = bool(key)
    return safe
