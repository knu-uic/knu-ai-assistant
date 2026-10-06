"""Durable latest-crawl snapshot used by the manager UI and crash recovery."""

from __future__ import annotations

import json
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import olefile
from PIL import Image

from extractors.hwp_structured import _binary_type, _decompress_bindata

from db.pool import sync_pool


def save_crawl_progress(snapshot: dict) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO crawl_run_state(singleton, snapshot, updated_at)
            VALUES (true, %s, now())
            ON CONFLICT (singleton) DO UPDATE
            SET snapshot = EXCLUDED.snapshot, updated_at = now()
            """,
            (json.dumps(snapshot, ensure_ascii=False),),
        )
        conn.commit()


def load_crawl_progress() -> dict:
    with sync_pool.connection() as conn:
        row = conn.execute(
            "SELECT snapshot FROM crawl_run_state WHERE singleton = true"
        ).fetchone()
    snapshot = dict(row[0]) if row and isinstance(row[0], dict) else {}
    _restore_legacy_hwp_substeps(snapshot)
    return snapshot


def _safe_attachment_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("._")
    return cleaned or "attachment.hwp"


def _legacy_hwp_evidence(filename: str) -> dict | None:
    root = Path(
        os.getenv("DOCUMENT_ASSETS_ROOT")
        or os.getenv("HWP_ASSETS_ROOT", "data/assets")
    ) / "hwp"
    if not root.is_dir():
        return None
    candidates = list(root.glob(f"*/{_safe_attachment_name(filename)}"))
    if not candidates:
        return None
    original = max(candidates, key=lambda path: path.stat().st_mtime)
    image_dir = original.parent / "images"
    extracted = [
        path for path in image_dir.iterdir()
        if path.is_file() and not path.name.endswith(".analysis.json")
    ] if image_dir.is_dir() else []
    analyzed = list(image_dir.glob("*.analysis.json")) if image_dir.is_dir() else []
    raster_total = 0
    analyzable_total = 0
    try:
        with olefile.OleFileIO(original) as document:
            for parts in document.listdir():
                if not parts or parts[0] != "BinData":
                    continue
                stream_name = "/".join(parts)
                binary = _decompress_bindata(document.openstream(stream_name).read())
                _suffix, _mime, is_raster = _binary_type(stream_name, binary)
                if not is_raster:
                    continue
                raster_total += 1
                try:
                    with Image.open(io.BytesIO(binary)) as image:
                        width, height = image.size
                    if width >= 96 and height >= 40 and width * height >= 12_000:
                        analyzable_total += 1
                except Exception:
                    pass
    except Exception:
        raster_total = len(extracted)
        analyzable_total = len(extracted)
    return {
        "original": original,
        "extracted": len(extracted),
        "analyzed": len(analyzed),
        "raster_total": raster_total,
        "analyzable_total": analyzable_total,
    }


def _restore_legacy_hwp_substeps(snapshot: dict) -> None:
    """Expose pre-checkpoint HWP evidence as read-only UI progress.

    Older runs persisted only ``다운로드·추출 중``. Their bundle is still
    ordered: image N is written immediately before its VLM call, so an
    interrupted legacy bundle with two images proves the preceding image was
    already attempted and the second was current.
    """
    for source in (snapshot.get("sources") or {}).values():
        for page in (source.get("pages") or {}).values():
            for notice in (page.get("notices") or {}).values():
                for attachment in (notice.get("attachments") or {}).values():
                    filename = str(attachment.get("name") or "")
                    if attachment.get("substeps") or not filename.lower().endswith(".hwp"):
                        continue
                    if attachment.get("status") not in {"processing", "pending", "complete"}:
                        continue
                    evidence = _legacy_hwp_evidence(filename)
                    if not evidence:
                        continue
                    attachment_complete = attachment.get("status") == "complete"
                    extracted = int(evidence["extracted"])
                    raster_total = int(evidence["raster_total"])
                    analysis_total = int(evidence["analyzable_total"])
                    analyzed = int(evidence["analyzed"])
                    if attachment_complete:
                        extracted = raster_total
                        analyzed = analysis_total
                    elif analyzed == 0 and attachment.get("status") == "processing" and extracted:
                        analyzed = min(analysis_total, max(0, extracted - 1))
                    attachment["substeps"] = [
                        {"key": "download", "label": "파일 다운로드", "status": "complete", "restored": True},
                        {"key": "document_structure", "label": "본문·구조 추출", "status": "complete" if attachment_complete or extracted else "processing", "restored": True},
                        {
                            "key": "internal_images", "label": "내부 이미지 추출",
                            "status": "complete" if attachment_complete or extracted >= raster_total else "processing",
                            "completed": extracted, "total": raster_total, "restored": True,
                        },
                        {
                            "key": "image_analysis", "label": "이미지 VLM 분석",
                            "status": "complete" if attachment_complete or analyzed >= analysis_total else "processing",
                            "completed": analyzed, "total": analysis_total, "restored": True,
                        },
                    ]


def mark_crawl_progress_interrupted() -> bool:
    snapshot = load_crawl_progress()
    if snapshot.get("status") not in {"running", "paused"}:
        return False
    snapshot.update({
        "status": "interrupted",
        "phase": "interrupted",
        "resumable": True,
        "error": "이전 실행이 정상적으로 끝나지 않아 수집이 중단되었습니다.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    save_crawl_progress(snapshot)
    return True


__all__ = [
    "save_crawl_progress",
    "load_crawl_progress",
    "mark_crawl_progress_interrupted",
]
