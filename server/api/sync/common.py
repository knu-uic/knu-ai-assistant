from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

DEFAULT_LMS_URL = "https://knulms.kongju.ac.kr"
DEFAULT_PORTAL_URL = "https://portal.kongju.ac.kr/index.jsp"
DEFAULT_STATE_PATH = ".secrets/lms_storage_state.json"
DEFAULT_CURRENT_USER_PATH = ".secrets/lms_current_user.json"
DEFAULT_DEBUG_DIR = ".secrets/lms_login_debug"


def build_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def canvas_token_path(state_path: Path) -> Path:
    return state_path.parent / "lms_canvas_token.txt"


__all__ = [
    "DEFAULT_LMS_URL",
    "DEFAULT_PORTAL_URL",
    "DEFAULT_STATE_PATH",
    "DEFAULT_CURRENT_USER_PATH",
    "DEFAULT_DEBUG_DIR",
    "build_url",
    "read_json",
    "write_json",
    "canvas_token_path",
]
