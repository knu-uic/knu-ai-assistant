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
import struct
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Callable

import olefile
import syhwp
from PIL import Image, ImageOps
from extractors.hwp2hwpx import convert_hwp_to_hwpx


ImageAnalyzer = Callable[[bytes, str, str, str], dict]


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


def _picture_bindata_ids(path: str) -> list[int]:
    """Return BinData ids in actual picture placement order.

    HWP's picture record stores the BinItem reference at byte offset 71. Using
    this reference is essential: BinData stream order is not placement order.
    """
    from syhwp._hwp5 import _read_hwp5

    _, sections = _read_hwp5(path)
    picture_tag = 16 + 69  # HWPTAG_SHAPE_COMPONENT_PICTURE
    result: list[int] = []
    for records in sections:
        for tag, _level, payload in records:
            if tag == picture_tag and len(payload) >= 73:
                binary_id = struct.unpack_from("<H", payload, 71)[0]
                if binary_id:
                    result.append(binary_id)
    return result


def _block_context_text(block: dict) -> str:
    if block.get("type") == "table":
        return " | ".join(
            str(cell.get("text") or "").strip()
            for cell in block.get("cells") or []
            if str(cell.get("text") or "").strip() and "[그림]" not in str(cell.get("text"))
        )
    return str(block.get("text") or block.get("alt") or "").strip()


def _clip_context(value: str, limit: int = 900) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


def _nearest_context(blocks: list[dict], index: int, direction: int) -> str:
    values: list[str] = []
    cursor = index + direction
    while 0 <= cursor < len(blocks) and len(values) < 2:
        text = _clip_context(_block_context_text(blocks[cursor]), 500)
        if text:
            values.append(text)
        cursor += direction
    if direction < 0:
        values.reverse()
    return "\n".join(values)


def _number_figure_placements(blocks: list[dict], picture_ids: list[int]) -> list[dict]:
    """Number every [그림] and bind it to its real BinData record + context."""
    snapshots = json.loads(json.dumps(blocks, ensure_ascii=False))
    figures: list[dict] = []
    reference_index = 0

    def replace_markers(text: str, block_index: int, cell: dict | None = None) -> str:
        nonlocal reference_index

        def replacement(_match: re.Match) -> str:
            nonlocal reference_index
            number = len(figures) + 1
            binary_id = picture_ids[reference_index] if reference_index < len(picture_ids) else None
            reference_index += 1
            location = ""
            if cell is not None:
                row_cells = [
                    str(candidate.get("text") or "").strip()
                    for candidate in snapshots[block_index].get("cells") or []
                    if candidate.get("row") == cell.get("row")
                    and str(candidate.get("text") or "").strip()
                ]
                location = " | ".join(row_cells)
            if not location:
                location = str(text or "").strip()
            before = _nearest_context(snapshots, block_index, -1)
            after = _nearest_context(snapshots, block_index, 1)
            context = "\n".join(
                part for part in (
                    f"[앞 문맥] {before}" if before else "",
                    f"[그림 위치] {_clip_context(location)}" if location else "",
                    f"[뒤 문맥] {after}" if after else "",
                ) if part
            )
            figures.append({
                "number": number,
                "label": f"그림 {number}",
                "binaryId": binary_id,
                "blockIndex": block_index,
                "cell": (
                    {"row": cell.get("row"), "column": cell.get("column")}
                    if cell is not None else None
                ),
                "context": context,
                "matchMethod": "hwp_picture_record_bin_item_id" if binary_id else "unmatched",
                "matchConfidence": 1.0 if binary_id else 0.0,
            })
            return f"[그림 {number}]"

        return re.sub(r"\[그림\]", replacement, text or "")

    for block_index, block in enumerate(blocks):
        if block.get("type") == "table":
            for cell in block.get("cells") or []:
                cell["text"] = replace_markers(str(cell.get("text") or ""), block_index, cell)
        elif block.get("type") == "image_reference":
            label = replace_markers("[그림]", block_index)
            block["alt"] = label.strip("[]")
        elif "[그림]" in str(block.get("text") or ""):
            block["text"] = replace_markers(str(block.get("text") or ""), block_index)
    return figures


def _number_markdown_figures(text: str, count: int) -> str:
    number = 0

    def replacement(_match: re.Match) -> str:
        nonlocal number
        number += 1
        return f"[그림 {number}]" if number <= count else "[그림]"

    return re.sub(r"\[그림\]", replacement, text or "")


def _figure_appendix(figures: list[dict]) -> str:
    entries: list[str] = []
    for figure in figures:
        analysis = figure.get("analysis") if isinstance(figure.get("analysis"), dict) else {}
        search_text = str(analysis.get("searchText") or "").strip()
        if not search_text or analysis.get("requiresReview"):
            continue
        entries.append(
            f"### [그림 {figure['number']}]\n\n"
            f"{figure.get('context', '').strip()}\n\n"
            f"[그림 설명] {search_text}"
        )
    if not entries:
        return ""
    return "## 문서 그림 설명\n\n" + "\n\n".join(entries)


def _figure_inline_text(figure: dict, *, html_breaks: bool = False) -> str:
    """검수를 통과한 그림 설명을 원래 배치 표시 직후에 넣는다."""
    analysis = figure.get("analysis") if isinstance(figure.get("analysis"), dict) else {}
    if analysis.get("requiresReview"):
        return ""
    description = str(analysis.get("description") or "").strip()
    ocr_text = str(analysis.get("ocrText") or "").strip()
    if not description and not ocr_text:
        description = str(analysis.get("searchText") or "").strip()
    lines = []
    if description:
        lines.append(f"[그림 설명] {description}")
    if ocr_text and ocr_text != description:
        lines.append(f"[그림 내 텍스트] {ocr_text}")
    separator = "<br>" if html_breaks else "\n"
    return separator.join(lines)


def _insert_figure_descriptions(text: str, figures: list[dict], *, markdown: bool) -> str:
    """번호가 붙은 그림 표시 바로 뒤에 문맥 기반 설명을 삽입한다.

    HWP 그림은 표 셀 안에 들어 있는 경우가 많다. Markdown 표를 깨지
    않도록 Markdown 출력은 ``<br>``로, 일반 텍스트는 줄바꿈으로 연결한다.
    """
    output = text or ""
    for figure in figures:
        number = int(figure["number"])
        marker = f"[그림 {number}]"
        inline = _figure_inline_text(figure, html_breaks=markdown)
        if not inline:
            continue
        replacement = f"{marker}{'<br>' if markdown else chr(10)}{inline}"
        output = output.replace(marker, replacement, 1)
    return output


def _figure_search_contents(figures: list[dict]) -> list[dict]:
    contents: list[dict] = []
    for figure in figures:
        analysis = figure.get("analysis") if isinstance(figure.get("analysis"), dict) else {}
        search_text = str(analysis.get("searchText") or "").strip()
        if not search_text or analysis.get("requiresReview"):
            continue
        contents.append({
            "number": figure["number"],
            "filename": figure.get("filename"),
            "text": (
                f"[그림 {figure['number']}]\n"
                f"{figure.get('context', '').strip()}\n"
                f"[그림 설명] {search_text}"
            ).strip(),
        })
    return contents


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
    figures_by_binary_id: dict[int, dict] | None = None,
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
            binary_match = re.search(r"BIN(\d+)", Path(stream_name).stem, re.I)
            binary_id = int(binary_match.group(1)) if binary_match else None
            figure = (figures_by_binary_id or {}).get(binary_id) if binary_id is not None else None
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
                                str((figure or {}).get("context") or ""),
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
                        if figure:
                            analysis["figureNumber"] = figure["number"]
                            analysis["documentContext"] = figure.get("context", "")
                        analyzed_count += 1
                        if analysis.get("kind") == "music_score":
                            music_count += 1
                except Exception as error:
                    analysis = {"status": "failed", "error": f"{type(error).__name__}: {error}"}

            asset = {
                "kind": "attachment_hwp_image" if is_raster else "attachment_hwp_binary",
                "filename": Path(stream_name).name,
                "storage_path": str(output_path),
                "mime_type": mime,
                "sha256": digest,
                "width": width,
                "height": height,
                "analysis": analysis,
                "binaryId": binary_id,
                "figure": (
                    {
                        "number": figure["number"],
                        "label": figure["label"],
                        "blockIndex": figure["blockIndex"],
                        "cell": figure.get("cell"),
                        "context": figure.get("context", ""),
                        "matchMethod": figure["matchMethod"],
                        "matchConfidence": figure["matchConfidence"],
                    }
                    if figure else None
                ),
                "order_idx": order,
            }
            assets.append(asset)
            if figure:
                figure.update({
                    "filename": asset["filename"],
                    "storagePath": asset["storage_path"],
                    "mimeType": asset["mime_type"],
                    "sha256": asset["sha256"],
                    "width": width,
                    "height": height,
                    "analysis": analysis,
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
        picture_ids = _picture_bindata_ids(source.name)

    blocks = [_block_dict(block) for block in document.blocks]
    figures = _number_figure_placements(blocks, picture_ids)
    figures_by_binary_id = {
        int(figure["binaryId"]): figure
        for figure in figures
        if figure.get("binaryId") is not None
    }
    markdown = _number_markdown_figures(
        _unicode_scalar_text(document.markdown.strip()), len(figures)
    )
    source_primary_text = _unicode_scalar_text(document.text.strip())
    primary_text = _number_markdown_figures(
        source_primary_text, len(figures)
    )
    binary_assets, binary_stats = _extract_binaries(
        data,
        bundle_dir,
        image_analyzer,
        source_primary_text,
        figures_by_binary_id,
    )
    # 이미지 분석이 끝난 뒤에만 원래 그림 위치에 검수된 설명을 삽입한다.
    # 그림별 독립 검색 청크는 _figure_search_contents에서 별도로 유지한다.
    markdown = _insert_figure_descriptions(markdown, figures, markdown=True)
    primary_text = _insert_figure_descriptions(primary_text, figures, markdown=False)
    figure_contents = _figure_search_contents(figures)
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
            "textTokenF1": round(_counter_f1(source_primary_text, converted_text), 6),
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
    text_agreement = _counter_f1(source_primary_text, secondary_text)
    length_ratio = (
        min(len(source_primary_text), len(secondary_text))
        / max(1, max(len(source_primary_text), len(secondary_text)))
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
        "primaryTextCharacters": len(source_primary_text),
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
        "figures": figures,
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
        "figure_contents": figure_contents,
    }
