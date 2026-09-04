"""Safe resolution for crawler-generated public notice assets."""
from pathlib import Path

from fastapi import HTTPException


ASSETS_ROOT = (Path(__file__).resolve().parents[1] / "data" / "assets").resolve()


def resolve_asset_path(storage_path: str) -> Path:
    value = Path(storage_path)
    api_root = Path(__file__).resolve().parents[1]
    candidate = value.resolve() if value.is_absolute() else (api_root / value).resolve()
    if not candidate.is_relative_to(ASSETS_ROOT):
        raise HTTPException(status_code=403, detail="허용되지 않은 자산 경로입니다.")
    return candidate
