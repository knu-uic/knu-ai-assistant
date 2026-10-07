"""Safe resolution for crawler-generated public notice assets."""
import os
import unicodedata
from pathlib import Path

from fastapi import HTTPException


_API_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = Path(
    os.getenv("DOCUMENT_ASSETS_ROOT")
    or os.getenv("HWP_ASSETS_ROOT")
    or (_API_ROOT / "data" / "assets")
).expanduser().resolve()


def resolve_asset_path(storage_path: str) -> Path:
    value = Path(storage_path)
    candidate = value.resolve() if value.is_absolute() else (_API_ROOT / value).resolve()
    # APFS commonly exposes Korean filenames in NFD while settings entered by
    # a user arrive as NFC. Path.is_relative_to compares code points and would
    # reject the same on-disk directory in that case. Both paths are resolved
    # before this normalized containment check, so symlink traversal remains
    # outside the allowed root.
    candidate_text = unicodedata.normalize("NFC", os.fspath(candidate))
    root_text = unicodedata.normalize("NFC", os.fspath(ASSETS_ROOT))
    try:
        inside_root = os.path.commonpath([candidate_text, root_text]) == root_text
    except ValueError:
        inside_root = False
    if not inside_root:
        raise HTTPException(status_code=403, detail="허용되지 않은 자산 경로입니다.")
    return candidate
