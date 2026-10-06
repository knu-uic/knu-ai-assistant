"""Local reranker model lifecycle for KNU Server Manager."""
from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from api.runtime_settings import DEFAULT_RERANKER_MODEL, load_settings

SUPPORTED_MODELS = (DEFAULT_RERANKER_MODEL,)
_LOCK = threading.RLock()
_DOWNLOAD = {"state": "idle", "model": None, "error": None}


def _cache_root() -> Path:
    explicit = os.getenv("HF_HUB_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    hf_home = Path(
        os.getenv("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    ).expanduser()
    return hf_home / "hub"


def _model_cache_path(model: str) -> Path:
    if model not in SUPPORTED_MODELS:
        raise ValueError(f"지원하지 않는 로컬 리랭커 모델입니다: {model}")
    return _cache_root() / f"models--{model.replace('/', '--')}"


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    seen: set[tuple[int, int]] = set()
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                stat = entry.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity not in seen:
                    seen.add(identity)
                    total += stat.st_size
        except OSError:
            continue
    return total


def _model_bytes(model: str) -> int:
    """Return logical model bytes, including Hugging Face shared blobs."""
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir(_cache_root())
        repo = next(
            (item for item in cache.repos if item.repo_id == model),
            None,
        )
        if repo is not None:
            return int(repo.size_on_disk)
    except Exception:
        pass
    return _directory_bytes(_model_cache_path(model))


def local_model_path(model: str) -> str | None:
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        path = Path(snapshot_download(
            model,
            cache_dir=str(_cache_root()),
            local_files_only=True,
        ))
        required = ("config.json", "tokenizer_config.json", "model.safetensors")
        if not all((path / name).is_file() for name in required):
            return None
        return str(path)
    except LocalEntryNotFoundError:
        return None


def reranker_status() -> dict:
    settings = load_settings()["reranker"]
    model = settings["model"]
    installed = local_model_path(model) is not None
    with _LOCK:
        download = dict(_DOWNLOAD)
    if not settings["enabled"]:
        effective = "disabled"
    elif download["state"] == "running":
        effective = "downloading"
    elif installed:
        effective = "ready"
    else:
        effective = "vector_fallback"
    return {
        **settings,
        "installed": installed,
        "bytes": _model_bytes(model),
        "cache_path": str(_model_cache_path(model)),
        "effective_status": effective,
        "download": download,
    }


def _download_model(model: str) -> None:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(model, cache_dir=str(_cache_root()))
        with _LOCK:
            _DOWNLOAD.update(state="complete", model=model, error=None)
    except Exception as exc:
        with _LOCK:
            _DOWNLOAD.update(state="failed", model=model, error=str(exc))


def start_reranker_download(model: str) -> dict:
    _model_cache_path(model)
    with _LOCK:
        if _DOWNLOAD["state"] == "running":
            return reranker_status()
        _DOWNLOAD.update(state="running", model=model, error=None)
    threading.Thread(
        target=_download_model,
        args=(model,),
        name="knu-reranker-download",
        daemon=True,
    ).start()
    return reranker_status()


def delete_reranker_model(model: str) -> dict:
    path = _model_cache_path(model)
    with _LOCK:
        if _DOWNLOAD["state"] == "running":
            raise RuntimeError("리랭커 모델 다운로드가 끝난 뒤 삭제하세요.")
    from retrieval.rerank import clear_reranker_runtime_cache

    clear_reranker_runtime_cache()
    deleted = False
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir(_cache_root())
        repo = next((item for item in cache.repos if item.repo_id == model), None)
        revisions = [revision.commit_hash for revision in repo.revisions] if repo else []
        if revisions:
            cache.delete_revisions(*revisions).execute()
            deleted = True
    except Exception:
        pass
    if not deleted and path.exists():
        shutil.rmtree(path)
    with _LOCK:
        _DOWNLOAD.update(state="idle", model=None, error=None)
    return reranker_status()
