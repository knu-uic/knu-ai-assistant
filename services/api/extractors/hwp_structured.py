"""HWP 5.x를 렌더러 없이 구조화하는 추출기.

원본 HWP, 구조 JSON, 검색용 Markdown, BinData 원본을 한 번에
보관한다. syhwp 구조 파서와 독립적인 문단 파서 결과를 비교해
자동 적재 여부를 판정한다.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Callable

import olefile
import syhwp
from PIL import Image, ImageOps
from extractors.hwp2hwpx import convert_hwp_to_hwpx


ImageAnalyzer = Callable[[bytes, str, str], dict]


def _unicode_scalar_text(value: str) -> str:
    """UTF-16 서로게이트 쌍을 합치고 단독 조각은 U+FFFD로 치환한다."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    output: list[str] = []
    index = 0
    while index < len(value):
        code = ord(value[index])
        if 0xD800 <= code <= 0xDBFF:
            if index + 1 < len(value):
                low = ord(value[index + 1])
                if 0xDC00 <= low <= 0xDFFF:
                    output.append(chr(0x10000 + ((code - 0xD800) << 10) + low - 0xDC00))
                    index += 2
                    continue
            output.append("\uFFFD")
        elif 0xDC00 <= code <= 0xDFFF:
            output.append("\uFFFD")
        else:
            output.append(value[index])
        index += 1
    return "".join(output)


def _json_safe(value):
    if isinstance(value, str):
        return _unicode_scalar_text(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("._")
    return cleaned or "attachment.hwp"


def _token_counter(text: str) -> Counter[str]:
    return Counter(re.findall(r"[가-힣A-Za-z0-9]+", (text or "").lower()))


def _counter_f1(primary: str, secondary: str) -> float:
    left = _token_counter(primary)
    right = _token_counter(secondary)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    overlap = sum((left & right).values())
    precision = overlap / sum(left.values())
    recall = overlap / sum(right.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _block_dict(block) -> dict:
    if isinstance(block, syhwp.Paragraph):
        return {"type": "paragraph", "text": _unicode_scalar_text(block.text)}
    if isinstance(block, syhwp.Table):
        return {
            "type": "table",
            "rows": block.n_rows,
            "columns": block.n_cols,
            "cells": [
                {
                    "row": cell.row,
                    "column": cell.col,
                    "rowSpan": cell.row_span,
                    "columnSpan": cell.col_span,
                    "text": _unicode_scalar_text(cell.text),
                }
                for cell in block.cells
            ],
        }
    if isinstance(block, syhwp.Equation):
        return {
            "type": "equation",
            "script": _unicode_scalar_text(block.script),
            "text": _unicode_scalar_text(block.text),
        }
    if isinstance(block, syhwp.Image):
        return {"type": "image_reference", "alt": _unicode_scalar_text(block.alt)}
    return {"type": "unknown", "text": _unicode_scalar_text(getattr(block, "text", ""))}


def _decompress_bindata(raw: bytes) -> bytes:
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        return raw


def _binary_type(name: str, data: bytes) -> tuple[str, str, bool]:
    suffix = Path(name).suffix.lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png", True
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg", True
    if data.startswith(b"BM"):
        return ".bmp", "image/bmp", True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif", True
    if data.startswith(b"\xd7\xcd\xc6\x9a"):
        return ".wmf", "image/wmf", False
    if data.startswith(b"%!PS-Adobe"):
        return suffix or ".eps", "application/postscript", False
    if data.startswith(b"\xd0\xcf\x11\xe0") or data[4:12] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".ole", "application/x-ole-storage", False
    return suffix or ".bin", "application/octet-stream", False


def _analysis_preview(data: bytes) -> tuple[bytes, str, int, int]:
    with Image.open(io.BytesIO(data)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, "JPEG", quality=92, optimize=True)
        return output.getvalue(), "image/jpeg", width, height


def _extract_binaries(
    data: bytes,
    bundle_dir: Path,
    image_analyzer: ImageAnalyzer | None,
    validation_text: str,
) -> tuple[list[dict], dict]:
    binary_dir = bundle_dir / "images"
    binary_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict] = []
    analysis_cache: dict[str, dict] = {}
    raster_count = 0
    analyzed_count = 0
    music_count = 0

    with olefile.OleFileIO(io.BytesIO(data)) as document:
        names = sorted(
            "/".join(parts)
            for parts in document.listdir()
            if parts and parts[0] == "BinData"
        )
        for order, stream_name in enumerate(names):
            binary = _decompress_bindata(document.openstream(stream_name).read())
            suffix, mime, is_raster = _binary_type(stream_name, binary)
            digest = hashlib.sha256(binary).hexdigest()
            output_name = f"{Path(stream_name).stem}_{digest[:12]}{suffix}"
            output_path = binary_dir / output_name
            if not output_path.exists():
                output_path.write_bytes(binary)

            analysis: dict = {}
            width = height = None
            if is_raster:
                raster_count += 1
                try:
                    preview, preview_mime, width, height = _analysis_preview(binary)
                    # 아이콘/선 조각은 원본만 보존하고 VLM 노이즈를 만들지 않는다.
                    should_analyze = width >= 96 and height >= 40 and width * height >= 12_000
                    if image_analyzer and should_analyze:
                        if digest not in analysis_cache:
                            analysis_cache[digest] = image_analyzer(
                                preview,
                                preview_mime,
                                Path(stream_name).name,
                            )
                        analysis = analysis_cache[digest]
                        if analysis.get("kind") == "music_score":
                            music = analysis.get("music") if isinstance(analysis.get("music"), dict) else {}
                            candidates = re.findall(
                                r"([가-힣 ]{2,12})\s*작사\s+([가-힣 ]{2,12})\s*작곡",
                                validation_text,
                            )
                            if len(candidates) == 1:
                                lyricist, composer = (
                                    re.sub(r"\s+", "", value) for value in candidates[0]
                                )
                                raw_lyricist = re.sub(r"\s+", "", str(music.get("lyricist") or ""))
                                raw_composer = re.sub(r"\s+", "", str(music.get("composer") or ""))
                                contradictions = []
                                if raw_lyricist and raw_lyricist != lyricist:
                                    contradictions.append("lyricist")
                                if raw_composer and raw_composer != composer:
                                    contradictions.append("composer")
                                music.update({
                                    "lyricist": lyricist,
                                    "composer": composer,
                                    "notationStatus": "preserved_as_image",
                                })
                                analysis["music"] = music
                                analysis["searchText"] = " ".join(
                                    value for value in (
                                        str(music.get("title") or ""), lyricist, composer
                                    ) if value
                                )
                                if contradictions:
                                    analysis.update({
                                        "requiresReview": True,
                                        "reviewReason": "vlm_conflicts_with_hwp_text",
                                        "contradictingFields": contradictions,
                                        "correctedFromDocumentText": True,
                                    })
                            else:
                                analysis["searchText"] = ""
                                analysis["requiresReview"] = True
                                analysis["reviewReason"] = "music_context_not_unique"
                        else:
                            analysis["searchText"] = "\n".join(
                                value.strip()
                                for value in (
                                    str(analysis.get("ocrText") or ""),
                                    str(analysis.get("description") or ""),
                                )
                                if value.strip()
                            )
                        analyzed_count += 1
                        if analysis.get("kind") == "music_score":
                            music_count += 1
                except Exception as error:
                    analysis = {"status": "failed", "error": f"{type(error).__name__}: {error}"}

            assets.append({
                "kind": "attachment_hwp_image" if is_raster else "attachment_hwp_binary",
                "filename": Path(stream_name).name,
                "storage_path": str(output_path),
                "mime_type": mime,
                "sha256": digest,
                "width": width,
                "height": height,
                "analysis": analysis,
                "order_idx": order,
            })

    stats = {
        "binaryCount": len(assets),
        "rasterImageCount": raster_count,
        "uniqueAnalyzedImageCount": len(analysis_cache),
        "analyzedReferenceCount": analyzed_count,
        "musicScoreCount": music_count,
        "binaryExtractionRatio": 1.0,
    }
    return assets, stats


def extract_hwp_structured(
    data: bytes,
    filename: str,
    *,
    secondary_text: str,
    assets_root: Path,
    image_analyzer: ImageAnalyzer | None = None,
    acceptance_threshold: float = 0.94,
) -> dict:
    """HWP를 구조화하고 재현 가능한 artifact bundle로 보관한다."""
    digest = hashlib.sha256(data).hexdigest()
    bundle_dir = assets_root / "hwp" / digest
    bundle_dir.mkdir(parents=True, exist_ok=True)
    original_path = bundle_dir / _safe_name(filename)
    original_path.write_bytes(data)

    with tempfile.NamedTemporaryFile(suffix=".hwp") as source:
        source.write(data)
        source.flush()
        document = syhwp.open(source.name)

    blocks = [_block_dict(block) for block in document.blocks]
    markdown = _unicode_scalar_text(document.markdown.strip())
    primary_text = _unicode_scalar_text(document.text.strip())
    binary_assets, binary_stats = _extract_binaries(
        data,
        bundle_dir,
        image_analyzer,
        primary_text,
    )
    conversion = convert_hwp_to_hwpx(data)
    converted_path: Path | None = None
    hwpx_validation = {
        "status": conversion["status"],
        "reason": conversion.get("reason"),
    }
    if conversion["status"] == "converted":
        converted_data = conversion["data"]
        converted_path = bundle_dir / "validation.hwpx"
        converted_path.write_bytes(converted_data)
        with tempfile.NamedTemporaryFile(suffix=".hwpx") as converted_source:
            converted_source.write(converted_data)
            converted_source.flush()
            converted_document = syhwp.open(converted_source.name)
        converted_text = _unicode_scalar_text(converted_document.text.strip())
        hwpx_validation.update({
            "bytes": len(converted_data),
            "textTokenF1": round(_counter_f1(primary_text, converted_text), 6),
            "textCharacters": len(converted_text),
            "paragraphCount": len(converted_document.paragraphs),
            "tableCount": len(converted_document.tables),
            "imageReferenceCount": sum(
                isinstance(block, syhwp.Image) for block in converted_document.blocks
            ),
        })

    table_blocks = [block for block in blocks if block["type"] == "table"]
    cells = [cell for table in table_blocks for cell in table["cells"]]
    valid_cells = sum(
        1
        for table in table_blocks
        for cell in table["cells"]
        if (
            0 <= cell["row"] < table["rows"]
            and 0 <= cell["column"] < table["columns"]
            and cell["rowSpan"] >= 1
            and cell["columnSpan"] >= 1
        )
    )
    # 셀이 없는 표도 정상이므로, 파싱된 셀의 좌표 범위만 검증한다.
    table_integrity = valid_cells / len(cells) if cells else 1.0
    text_agreement = _counter_f1(primary_text, secondary_text)
    length_ratio = (
        min(len(primary_text), len(secondary_text))
        / max(1, max(len(primary_text), len(secondary_text)))
    )
    quality_score = (
        text_agreement * 0.65
        + length_ratio * 0.15
        + table_integrity * 0.10
        + binary_stats["binaryExtractionRatio"] * 0.10
    )
    if conversion["status"] == "converted":
        quality_score = quality_score * 0.8 + hwpx_validation["textTokenF1"] * 0.2
    conversion_discrepancy = (
        conversion["status"] == "failed"
        or (
            conversion["status"] == "converted"
            and hwpx_validation["textTokenF1"] < acceptance_threshold
        )
    )
    review_required = quality_score < acceptance_threshold or conversion_discrepancy

    quality = {
        "status": "review_required" if review_required else "accepted",
        "score": round(quality_score, 6),
        "acceptanceThreshold": acceptance_threshold,
        "textTokenF1": round(text_agreement, 6),
        "textLengthRatio": round(length_ratio, 6),
        "tableIntegrity": round(table_integrity, 6),
        "primaryTextCharacters": len(primary_text),
        "secondaryTextCharacters": len(secondary_text),
        "paragraphCount": sum(block["type"] == "paragraph" for block in blocks),
        "tableCount": len(table_blocks),
        "tableCellCount": len(cells),
        "equationCount": sum(block["type"] == "equation" for block in blocks),
        "imageReferenceCount": sum(block["type"] == "image_reference" for block in blocks),
        **binary_stats,
        "hwpToHwpx": hwpx_validation,
    }

    structure = _json_safe({
        "schemaVersion": "codmes-hwp-1",
        "source": {
            "filename": filename,
            "sha256": digest,
            "bytes": len(data),
            "format": document.format,
            "formatVersion": document.version,
        },
        "quality": quality,
        "blocks": blocks,
        "binaries": binary_assets,
    })
    markdown_path = bundle_dir / "document.md"
    structure_path = bundle_dir / "document.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    structure_path.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "markdown": markdown,
        "primary_text": primary_text,
        "quality": quality,
        "review_required": review_required,
        "bundle_dir": str(bundle_dir),
        "original_path": str(original_path),
        "markdown_path": str(markdown_path),
        "structure_path": str(structure_path),
        "converted_hwpx_path": str(converted_path) if converted_path else None,
        "binary_assets": binary_assets,
    }
