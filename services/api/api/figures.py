"""Map figure references in retrieved text to renderable notice images."""
from __future__ import annotations

from typing import Any


def related_figures(figures: Any, text: str) -> list[dict]:
    if not isinstance(figures, list):
        return []
    result: list[dict] = []
    for raw in figures:
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get("number"))
            asset_id = int(raw.get("asset_id"))
        except (TypeError, ValueError):
            continue
        if asset_id <= 0:
            continue
        marker = str(raw.get("marker") or f"[그림 {number}]")
        if marker not in (text or ""):
            continue
        result.append({
            "asset_id": asset_id,
            "reference": f"[그림:{asset_id}]",
            "number": number,
            "label": raw.get("label") or f"그림 {number}",
            "filename": raw.get("filename"),
            "description": raw.get("description"),
            "context": raw.get("context"),
            "url": raw.get("url") or f"/api/notice-assets/{raw.get('asset_id')}/content",
        })
    return result


def collect_related_figures(*groups: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[int] = set()
    for group in groups:
        for figure in group or []:
            asset_id = figure.get("asset_id")
            if not isinstance(asset_id, int) or asset_id in seen:
                continue
            seen.add(asset_id)
            result.append(figure)
    return result
