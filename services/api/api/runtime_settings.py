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
ALLOWED_REFINE_PROVIDERS = ("ollama", "lmstudio", "openai", "google", "openai-codex")
ALLOWED_SCHOOL_CHAT_PROVIDERS = ("ollama", "lmstudio", "openai", "google")
ALLOWED_EMBEDDING_PROVIDERS = ("ollama", "lmstudio", "openai", "google")
ALLOWED_RERANKER_PROVIDERS = ("local",)
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_CHUNK_SIZE = 280
DEFAULT_CHUNK_OVERLAP = 80

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
    embedding_provider = (
        (os.getenv("EMBEDDING_PROVIDER") or "ollama")
        .strip().lower().replace("local", "ollama")
    )
    try:
        embedding_dimension = int(os.getenv("EMBEDDING_DIM", "1024"))
    except ValueError:
        embedding_dimension = 1024
    embedding_key = ""
    if embedding_provider == "openai":
        embedding_key = os.getenv("OPENAI_API_KEY") or ""
    elif embedding_provider == "google":
        embedding_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    try:
        reranker_max_length = max(128, int(os.getenv("RERANKER_MAX_LENGTH", "512")))
    except ValueError:
        reranker_max_length = 512
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
        "refine": {
            "provider": provider if provider != "openai-codex" else "lmstudio",
            "model": os.getenv("LLM_MODEL") or "",
            "base_url": os.getenv("OPENAI_COMPAT_BASE_URL") or "http://127.0.0.1:1234/v1",
            "api_key": key if provider != "openai-codex" else "",
        },
        "school_chat": {
            "enabled": False,
            "provider": "ollama",
            "model": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
        },
        "embedding": {
            "provider": embedding_provider,
            "model": os.getenv("EMBEDDING_MODEL") or "bge-m3:latest",
            "base_url": os.getenv("OPENAI_COMPAT_BASE_URL") or "http://127.0.0.1:11434/v1",
            "dimension": embedding_dimension,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
            "api_key": embedding_key,
        },
        "reranker": {
            "enabled": _env_bool("RERANKER_ENABLED", True),
            "provider": "local",
            "model": os.getenv("RERANKER_MODEL") or DEFAULT_RERANKER_MODEL,
            "max_length": reranker_max_length,
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
    # Older settings had one VLM selection for both image extraction and notice
    # refinement. Copy it once on migration, then keep the two settings separate.
    legacy_refine = vlm_raw if provider != "openai-codex" else defaults["refine"]
    refine_raw = raw.get("refine") if isinstance(raw.get("refine"), dict) else legacy_refine
    refine_provider = str(refine_raw.get("provider", defaults["refine"]["provider"])).strip().lower()
    if refine_provider not in ALLOWED_REFINE_PROVIDERS:
        refine_provider = defaults["refine"]["provider"]
    school_raw = raw.get("school_chat") if isinstance(raw.get("school_chat"), dict) else {}
    school_provider = str(school_raw.get("provider", defaults["school_chat"]["provider"])).strip().lower()
    if school_provider not in ALLOWED_SCHOOL_CHAT_PROVIDERS:
        school_provider = defaults["school_chat"]["provider"]
    school_enabled = school_raw.get("enabled", False) is True
    embedding_raw = raw.get("embedding") if isinstance(raw.get("embedding"), dict) else {}
    embedding_provider = str(
        embedding_raw.get("provider", defaults["embedding"]["provider"])
    ).strip().lower().replace("local", "ollama")
    if embedding_provider not in ALLOWED_EMBEDDING_PROVIDERS:
        embedding_provider = defaults["embedding"]["provider"]
    try:
        embedding_dimension = int(
            embedding_raw.get("dimension", defaults["embedding"]["dimension"])
        )
    except (TypeError, ValueError):
        embedding_dimension = defaults["embedding"]["dimension"]
    try:
        embedding_chunk_size = min(4000, max(
            64, int(embedding_raw.get("chunk_size", DEFAULT_CHUNK_SIZE)),
        ))
    except (TypeError, ValueError):
        embedding_chunk_size = DEFAULT_CHUNK_SIZE
    try:
        embedding_chunk_overlap = max(
            0, int(embedding_raw.get("chunk_overlap", DEFAULT_CHUNK_OVERLAP)),
        )
    except (TypeError, ValueError):
        embedding_chunk_overlap = DEFAULT_CHUNK_OVERLAP
    embedding_chunk_overlap = min(embedding_chunk_overlap, embedding_chunk_size - 1)
    reranker_raw = raw.get("reranker") if isinstance(raw.get("reranker"), dict) else {}
    reranker_provider = str(
        reranker_raw.get("provider", defaults["reranker"]["provider"])
    ).strip().lower()
    if reranker_provider not in ALLOWED_RERANKER_PROVIDERS:
        reranker_provider = defaults["reranker"]["provider"]
    reranker_enabled_raw = reranker_raw.get("enabled", defaults["reranker"]["enabled"])
    reranker_enabled = (
        reranker_enabled_raw.strip().lower() not in {"0", "false", "off", "no"}
        if isinstance(reranker_enabled_raw, str)
        else bool(reranker_enabled_raw)
    )
    try:
        reranker_max_length = min(2048, max(
            128,
            int(reranker_raw.get("max_length", defaults["reranker"]["max_length"])),
        ))
    except (TypeError, ValueError):
        reranker_max_length = defaults["reranker"]["max_length"]
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
        "refine": {
            "provider": refine_provider,
            "model": str(refine_raw.get("model", defaults["refine"]["model"])).strip(),
            "base_url": str(refine_raw.get("base_url", defaults["refine"]["base_url"])).strip(),
            "api_key": str(refine_raw.get("api_key") or ""),
        },
        "school_chat": {
            "enabled": school_enabled,
            "provider": school_provider,
            "model": str(school_raw.get("model") or "").strip(),
            "base_url": str(school_raw.get("base_url") or (
                "http://127.0.0.1:11434/v1" if school_provider == "ollama"
                else "http://127.0.0.1:1234/v1" if school_provider == "lmstudio" else ""
            )).strip(),
            "api_key": str(school_raw.get("api_key") or ""),
        },
        "embedding": {
            "provider": embedding_provider,
            "model": str(
                embedding_raw.get("model", defaults["embedding"]["model"])
            ).strip(),
            "base_url": str(
                embedding_raw.get("base_url", defaults["embedding"]["base_url"])
            ).strip(),
            "dimension": max(1, embedding_dimension),
            "chunk_size": embedding_chunk_size,
            "chunk_overlap": embedding_chunk_overlap,
            "api_key": str(
                embedding_raw.get("api_key", defaults["embedding"]["api_key"])
            ),
        },
        "reranker": {
            "enabled": reranker_enabled,
            "provider": reranker_provider,
            "model": str(
                reranker_raw.get("model", defaults["reranker"]["model"])
            ).strip() or DEFAULT_RERANKER_MODEL,
            "max_length": reranker_max_length,
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
    refine_key = safe["refine"].pop("api_key", "")
    safe["refine"]["has_api_key"] = bool(refine_key)
    school_key = safe["school_chat"].pop("api_key", "")
    safe["school_chat"]["has_api_key"] = bool(school_key)
    embedding_key = safe["embedding"].pop("api_key", "")
    safe["embedding"]["has_api_key"] = bool(embedding_key)
    return safe
