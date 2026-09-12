"""Structured table extraction for raster-origin PDF pages."""
from __future__ import annotations

import io
import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any, Protocol
from pathlib import Path

import pymupdf
from PIL import Image

from extractors.table_validation import validate_extracted_tables


RENDER_DPI = 250
MIN_HORIZONTAL_LINES = 5
MAX_SEGMENT_WIDTH_RATIO = 0.70
SEGMENT_OVERLAP_PX = 24


class TableBackend(Protocol):
    def ocr(self, image: Image.Image) -> list[dict[str, Any]]: ...
    def structure(self, image: Image.Image) -> dict[str, Any]: ...


def _result_json(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", result)
    value = value() if callable(value) else value
    return value.get("res", value) if isinstance(value, dict) else {}


class PaddleTableBackend:
    """Lazy PaddleOCR adapter so ordinary API imports do not load ML models."""

    def __init__(self) -> None:
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(
            lang="korean",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        self._structure = None

    def ocr(self, image: Image.Image) -> list[dict[str, Any]]:
        import numpy as np

        results = list(self._ocr.predict(
            np.asarray(image.convert("RGB")),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        ))
        if not results:
            return []
        raw = _result_json(results[0])
        texts = raw.get("rec_texts") or []
        scores = raw.get("rec_scores") or []
        boxes = raw.get("rec_boxes") or raw.get("dt_boxes") or []
        items = []
        for index, text in enumerate(texts):
            if index >= len(boxes):
                break
            box = boxes[index]
            if len(box) == 4 and not isinstance(box[0], (list, tuple)):
                bbox = [float(value) for value in box]
            elif box and not isinstance(box[0], (list, tuple)):
                xs = [float(value) for value in box[0::2]]
                ys = [float(value) for value in box[1::2]]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            else:
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            items.append({
                "id": index,
                "text": str(text).strip(),
                "confidence": float(scores[index]) if index < len(scores) else None,
                "bbox": bbox,
            })
        return [item for item in items if item["text"]]

    def structure(self, image: Image.Image) -> dict[str, Any]:
        import numpy as np
        from paddleocr import TableStructureRecognition

        if self._structure is None:
            self._structure = TableStructureRecognition(model_name="SLANet_plus")

        results = list(self._structure.predict(np.asarray(image.convert("RGB"))))
        if not results:
            return {"html": "", "boxes": [], "confidence": 0.0}
        raw = _result_json(results[0])
        structure = raw.get("structure") or []
        html = "".join(str(token) for token in structure)
        return {
            "html": html,
            "boxes": raw.get("bbox") or raw.get("boxes") or [],
            "confidence": float(raw.get("structure_score") or 0.0),
        }


@lru_cache(maxsize=1)
def _default_backend() -> PaddleTableBackend:
    """Load table models once per long-running worker process."""
    return PaddleTableBackend()


def _line_bands(mask: Any, *, axis: int, minimum: int) -> list[tuple[int, int]]:
    import numpy as np

    values = np.count_nonzero(mask, axis=axis)
    indices = np.flatnonzero(values >= minimum).tolist()
    if not indices:
        return []
    bands: list[tuple[int, int]] = []
    start = previous = indices[0]
    for value in indices[1:]:
        if value > previous + 1:
            bands.append((start, previous + 1))
            start = value
        previous = value
    bands.append((start, previous + 1))
    return bands


def _rule_masks(image: Image.Image) -> tuple[Any, Any, Any]:
    """Return binarized pixels and long horizontal/vertical ruling masks."""
    import cv2
    import numpy as np

    gray = np.asarray(image.convert("L"))
    # Local thresholding retains pale rules from scans. A single Otsu threshold
    # dropped the faint line above the final total in the curriculum fixture.
    block_size = max(15, min(51, (min(gray.shape) // 40) | 1))
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, block_size, 12,
    )
    height, width = gray.shape
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 24), 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(24, height // 40))),
    )
    return binary, horizontal, vertical


def _is_grid_like_region(image: Image.Image) -> bool:
    """Reject decorative frames, code boxes, and diagrams before OCR/model use."""
    import cv2
    import numpy as np

    _binary, horizontal, _vertical = _rule_masks(image)
    height, width = np.asarray(image).shape[:2]
    horizontal_bands = _line_bands(
        horizontal, axis=1, minimum=max(30, int(width * 0.25)),
    )
    if len(horizontal_bands) < MIN_HORIZONTAL_LINES:
        return False
    centers = np.asarray([(start + end - 1) / 2 for start, end in horizontal_bands])
    gaps = np.diff(centers)
    if len(gaps) and float(np.std(gaps) / max(1.0, np.mean(gaps))) > 0.85:
        return False

    # Use conservative global thresholding for this gate. Adaptive thresholding
    # preserves pale table rules, but can turn photographs/textures into hundreds
    # of fake vertical strokes.
    gray = np.asarray(image.convert("L"))
    otsu = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]
    persistent_vertical = cv2.morphologyEx(
        otsu,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, height // 30))),
    )
    vertical_bands = _line_bands(
        persistent_vertical, axis=0, minimum=max(8, int(height * 0.10)),
    )
    max_rule_width = max(10, int(width * 0.012))
    vertical_bands = [
        band for band in vertical_bands if band[1] - band[0] <= max_rule_width
    ]
    return len(vertical_bands) >= 3


def _restore_missing_regular_boundaries(boundaries: list[int]) -> list[int]:
    """Restore a single faint rule when neighboring row spacing proves it exists."""
    if len(boundaries) < 5:
        return boundaries
    gaps = sorted(
        boundaries[index + 1] - boundaries[index]
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] > boundaries[index]
    )
    # Use the smaller, regular population so whitespace between separate tables
    # does not become the expected row height.
    regular = gaps[:max(3, int(len(gaps) * 0.70))]
    expected = regular[len(regular) // 2]
    if expected < 5:
        return boundaries
    restored = [boundaries[0]]
    for left, right in zip(boundaries, boundaries[1:]):
        ratio = (right - left) / expected
        multiple = round(ratio)
        if 2 <= multiple <= 3 and abs(ratio - multiple) <= 0.12:
            restored.extend(
                round(left + (right - left) * part / multiple)
                for part in range(1, multiple)
            )
        restored.append(right)
    return restored


def detect_table_regions(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Detect ruled-table regions by geometry, independent of their text."""
    import cv2
    import numpy as np

    height, width = np.asarray(image).shape[:2]
    _binary, horizontal, vertical = _rule_masks(image)
    horizontal_bands = _line_bands(horizontal, axis=1, minimum=max(30, int(width * 0.20)))
    if len(horizontal_bands) < MIN_HORIZONTAL_LINES:
        return []

    gaps = [horizontal_bands[i + 1][0] - horizontal_bands[i][1] for i in range(len(horizontal_bands) - 1)]
    positive_gaps = sorted(gap for gap in gaps if gap > 0)
    median_gap = positive_gaps[len(positive_gaps) // 2] if positive_gaps else 20
    # Scanned rules are often faint around colored fills or page folds.  Treat
    # vertically adjacent, similarly wide ruled blocks as one table until a
    # genuinely large whitespace break appears; the next stage safely splits a
    # tall region back into model-sized sections at real horizontal borders.
    separation = max(int(height * 0.12), median_gap * 6)
    groups: list[list[tuple[int, int]]] = [[horizontal_bands[0]]]
    for band in horizontal_bands[1:]:
        if band[0] - groups[-1][-1][1] > separation:
            groups.append([band])
        else:
            groups[-1].append(band)

    regions = []
    combined = cv2.bitwise_or(horizontal, vertical)
    for group in groups:
        if len(group) < MIN_HORIZONTAL_LINES:
            continue
        y0 = max(0, group[0][0] - 4)
        y1 = min(height, group[-1][1] + 4)
        xs = np.flatnonzero(np.count_nonzero(combined[y0:y1], axis=0) >= max(12, int((y1 - y0) * 0.08)))
        if len(xs) < 2:
            continue
        x0, x1 = max(0, int(xs[0]) - 4), min(width, int(xs[-1]) + 5)
        region = (x0, y0, x1, y1)
        if (
            (x1 - x0) >= width * 0.30
            and (y1 - y0) >= 80
            and _is_grid_like_region(image.crop(region))
        ):
            regions.append(region)
    return regions


def rows_from_ruled_grid(
    image: Image.Image,
    region: tuple[int, int, int, int],
    ocr_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    """Build cells from visible rules instead of inferring them with a model."""
    import cv2
    import numpy as np

    x0, y0, _x1, _y1 = region
    binary, horizontal, long_vertical = _rule_masks(image.crop(region))
    height, width = binary.shape
    horizontal_bands = _line_bands(
        horizontal, axis=1, minimum=max(30, int(width * 0.25)),
    )
    if len(horizontal_bands) < MIN_HORIZONTAL_LINES:
        return [], 0.0

    y_boundaries = _restore_missing_regular_boundaries([
        int(round((start + end - 1) / 2)) for start, end in horizontal_bands
    ])
    max_rule_width = max(10, int(width * 0.012))
    global_vertical_bands = _line_bands(
        long_vertical, axis=0, minimum=max(12, int(height * 0.04)),
    )
    global_vertical_bands = [
        band for band in global_vertical_bands
        if band[1] - band[0] <= max_rule_width
    ]
    rows: list[dict[str, Any]] = []
    horizontal_coverages = [
        min(1.0, float(np.count_nonzero(horizontal[start:end])) / max(1, (end - start) * width))
        for start, end in horizontal_bands
    ]
    vertical_coverages: list[float] = []
    for local_top, local_bottom in zip(y_boundaries, y_boundaries[1:]):
        row_height = local_bottom - local_top
        if row_height < 5:
            continue
        row_pixels = binary[local_top:local_bottom, :]
        vertical = cv2.morphologyEx(
            row_pixels,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (1, max(5, int(row_height * 0.58)))
            ),
        )
        # Only consider globally recurring rule positions. Otherwise tall glyph
        # strokes (notably the digits in "140") become false cell boundaries.
        bands = []
        for band_index, band in enumerate(global_vertical_bands):
            band_start, band_end = band
            pixels = np.count_nonzero(vertical[:, band_start:band_end])
            is_outer_rule = band_index in {0, len(global_vertical_bands) - 1}
            if is_outer_rule or pixels >= max(4, int(row_height * max(1, band_end - band_start) * 0.20)):
                bands.append(band)
        x_boundaries = [int(round((start + end - 1) / 2)) for start, end in bands]
        if len(x_boundaries) < 2:
            continue
        left, right = x_boundaries[0], x_boundaries[-1]
        if right - left < width * 0.30:
            continue
        x_boundaries = [value for value in x_boundaries if left <= value <= right]
        vertical_coverages.extend(
            min(1.0, float(np.count_nonzero(vertical[:, max(0, value - 1):value + 2])) / max(1, row_height * 3))
            for value in x_boundaries
        )

        cells = []
        for column, (local_left, local_right) in enumerate(zip(x_boundaries, x_boundaries[1:])):
            if local_right - local_left < 3:
                continue
            bbox = [
                float(x0 + local_left), float(y0 + local_top),
                float(x0 + local_right), float(y0 + local_bottom),
            ]
            matches = sorted(
                (item for item in ocr_items if _inside(item, bbox)),
                key=lambda item: (item["bbox"][1], item["bbox"][0]),
            )
            scores = [float(item["confidence"]) for item in matches if item.get("confidence") is not None]
            cells.append({
                "column": column,
                "rowspan": 1,
                "colspan": 1,
                "bbox": [round(value, 2) for value in bbox],
                "text": " ".join(item["text"] for item in matches).strip(),
                "confidence": round(sum(scores) / len(scores), 4) if scores else None,
                "sourceOcrIds": [item["id"] for item in matches],
            })
        if not cells:
            continue
        row_text = " | ".join(cell["text"] for cell in cells if cell["text"])
        if not row_text:
            continue
        rows.append({
            "bbox": [
                min(cell["bbox"][0] for cell in cells), float(y0 + local_top),
                max(cell["bbox"][2] for cell in cells), float(y0 + local_bottom),
            ],
            "cells": cells,
            "text": row_text,
        })

    confidence_values = horizontal_coverages + vertical_coverages
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    return rows, round(confidence, 4)


def split_table_region(
    region: tuple[int, int, int, int],
    image: Image.Image,
) -> list[tuple[int, int, int, int]]:
    """Split tall tables at detected horizontal borders with a small overlap."""
    import cv2
    import numpy as np

    x0, y0, x1, y1 = region
    maximum_height = max(500, int((x1 - x0) * MAX_SEGMENT_WIDTH_RATIO))
    if y1 - y0 <= maximum_height:
        return [region]

    crop = np.asarray(image.crop(region).convert("L"))
    binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, crop.shape[1] // 24), 1)),
    )
    bands = _line_bands(horizontal, axis=1, minimum=max(30, int(crop.shape[1] * 0.25)))
    boundaries = [int((start + end) / 2) + y0 for start, end in bands]
    segments = []
    start = y0
    while y1 - start > maximum_height:
        target = start + maximum_height
        candidates = [value for value in boundaries if start + maximum_height * 0.55 <= value <= target]
        end = max(candidates) if candidates else target
        segments.append((x0, start, x1, min(y1, end + SEGMENT_OVERLAP_PX)))
        start = max(start + 1, end - SEGMENT_OVERLAP_PX)
    segments.append((x0, start, x1, y1))
    return segments


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, int]]] = []
        self._row: list[dict[str, int]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            values = dict(attrs)
            self._row.append({
                "rowspan": max(1, int(values.get("rowspan") or 1)),
                "colspan": max(1, int(values.get("colspan") or 1)),
            })

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _rect(box: Any, offset_x: int = 0, offset_y: int = 0) -> list[float]:
    if len(box) == 4 and not isinstance(box[0], (list, tuple)):
        x0, y0, x1, y1 = [float(value) for value in box]
    elif box and not isinstance(box[0], (list, tuple)):
        xs = [float(value) for value in box[0::2]]
        ys = [float(value) for value in box[1::2]]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    else:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return [x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y]


def _inside(item: dict[str, Any], bbox: list[float]) -> bool:
    x0, y0, x1, y1 = item["bbox"]
    center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
    return bbox[0] - 3 <= center_x <= bbox[2] + 3 and bbox[1] - 3 <= center_y <= bbox[3] + 3


def _inside_region(item: dict[str, Any], region: tuple[int, int, int, int]) -> bool:
    return _inside(item, [float(value) for value in region])


def rows_from_structure(
    structure: dict[str, Any],
    ocr_items: list[dict[str, Any]],
    *,
    offset_x: int = 0,
    offset_y: int = 0,
) -> list[dict[str, Any]]:
    parser = _TableHTMLParser()
    parser.feed(str(structure.get("html") or ""))
    boxes = structure.get("boxes") or []
    box_index = 0
    rows = []
    for raw_row in parser.rows:
        cells = []
        column = 0
        for raw_cell in raw_row:
            if box_index >= len(boxes):
                break
            bbox = _rect(boxes[box_index], offset_x, offset_y)
            box_index += 1
            matches = sorted(
                (item for item in ocr_items if _inside(item, bbox)),
                key=lambda item: (item["bbox"][1], item["bbox"][0]),
            )
            text = " ".join(item["text"] for item in matches).strip()
            scores = [float(item["confidence"]) for item in matches if item.get("confidence") is not None]
            cells.append({
                "column": column,
                "rowspan": raw_cell["rowspan"],
                "colspan": raw_cell["colspan"],
                "bbox": [round(value, 2) for value in bbox],
                "text": text,
                "confidence": round(sum(scores) / len(scores), 4) if scores else None,
                "sourceOcrIds": [item["id"] for item in matches],
            })
            column += raw_cell["colspan"]
        if not cells:
            continue
        row_bbox = [
            min(cell["bbox"][0] for cell in cells),
            min(cell["bbox"][1] for cell in cells),
            max(cell["bbox"][2] for cell in cells),
            max(cell["bbox"][3] for cell in cells),
        ]
        row_text = " | ".join(cell["text"] for cell in cells if cell["text"])
        rows.append({"bbox": row_bbox, "cells": cells, "text": row_text})
    return rows


def _dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    removed = 0
    for row in sorted(rows, key=lambda value: (value["bbox"][1], value["bbox"][0])):
        center = (row["bbox"][1] + row["bbox"][3]) / 2
        normalized = re.sub(r"\s+", "", row.get("text") or "")
        duplicate_index = None
        for index in range(max(0, len(kept) - 4), len(kept)):
            other = kept[index]
            other_center = (other["bbox"][1] + other["bbox"][3]) / 2
            other_text = re.sub(r"\s+", "", other.get("text") or "")
            similar = bool(normalized and other_text) and SequenceMatcher(None, normalized, other_text).ratio() >= 0.86
            if abs(center - other_center) <= 12 and (similar or not normalized or not other_text):
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(row)
            continue
        removed += 1
        old_scores = [cell["confidence"] for cell in kept[duplicate_index]["cells"] if cell.get("confidence") is not None]
        new_scores = [cell["confidence"] for cell in row["cells"] if cell.get("confidence") is not None]
        if (sum(new_scores) / len(new_scores) if new_scores else 0) > (sum(old_scores) / len(old_scores) if old_scores else 0):
            kept[duplicate_index] = row
    return kept, removed


def format_tables_for_retrieval(tables: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    blocks = []
    for table_index, table in enumerate(tables, start=1):
        lines = [
            f"[PDF {table['pageNumber']}페이지 표 {table_index}]",
            f"[표 검증: {validation['status']}]",
        ]
        for row_index, row in enumerate(table.get("rows") or []):
            marker = "[표 헤더]" if row_index == 0 else "[행]"
            if row.get("text"):
                lines.append(f"{marker} {row['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def extract_scanned_pdf_tables(
    data: bytes,
    pdf_structure: dict[str, Any],
    *,
    backend: TableBackend | None = None,
) -> dict[str, Any]:
    """Extract ruled tables from raster pages; fail closed to the caller's VLM path."""
    if os.getenv("PDF_TABLE_ANALYSIS_ENABLED", "true").lower() in {"0", "false", "no"}:
        return {"status": "disabled", "tables": [], "text": "", "validation": {}}
    pages_by_number = {int(page["pageNumber"]): page for page in pdf_structure.get("pages") or []}
    document = pymupdf.open(stream=data, filetype="pdf")
    all_tables = []
    outside_blocks: list[str] = []
    total_ocr_items = assigned_ocr_items = duplicate_rows_removed = 0
    matrix = pymupdf.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    try:
        for page in document:
            page_number = page.number + 1
            page_info = pages_by_number.get(page_number, {})
            if (
                not page_info.get("requiresVisualOcr")
                or page_info.get("renderType") != "raster_scan"
            ):
                continue
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            regions = detect_table_regions(image)
            if not regions:
                continue
            if backend is None:
                try:
                    backend = _default_backend()
                except Exception as error:
                    return {
                        "status": "unavailable",
                        "tables": [],
                        "text": "",
                        "validation": {},
                        "error": f"{type(error).__name__}: {error}",
                    }
            ocr_items = backend.ocr(image)
            table_ocr_items = [
                item for item in ocr_items
                if any(_inside_region(item, region) for region in regions)
            ]
            outside_items = sorted(
                (item for item in ocr_items if item not in table_ocr_items),
                key=lambda item: (item["bbox"][1], item["bbox"][0]),
            )
            if outside_items:
                outside_blocks.append(
                    f"[PDF {page_number}페이지 본문]\n"
                    + "\n".join(item["text"] for item in outside_items)
                )
            total_ocr_items += len(table_ocr_items)
            for region in regions:
                rows, structure_confidence = rows_from_ruled_grid(image, region, table_ocr_items)
                structure_engine = "opencv-grid"
                region_items = [item for item in table_ocr_items if _inside_region(item, region)]
                grid_ids = {
                    source_id
                    for row in rows
                    for cell in row.get("cells") or []
                    for source_id in cell.get("sourceOcrIds") or []
                }
                grid_assignment = len(grid_ids) / len(region_items) if region_items else 0.0
                if not rows or grid_assignment < 0.55:
                    rows = []
                    confidences = []
                    for segment in split_table_region(region, image):
                        segment_x0, segment_y0, segment_x1, segment_y1 = segment
                        structure = backend.structure(image.crop(segment))
                        confidences.append(float(structure.get("confidence") or 0.0))
                        rows.extend(rows_from_structure(
                            structure, table_ocr_items,
                            offset_x=segment_x0, offset_y=segment_y0,
                        ))
                    structure_confidence = (
                        round(sum(confidences) / len(confidences), 4) if confidences else 0.0
                    )
                    structure_engine = "slanet-plus"
                rows, removed = _dedupe_rows(rows)
                duplicate_rows_removed += removed
                if not rows:
                    continue
                ids = {
                    source_id
                    for row in rows
                    for cell in row.get("cells") or []
                    for source_id in cell.get("sourceOcrIds") or []
                }
                assigned_ocr_items += len(ids)
                all_tables.append({
                    "pageNumber": page_number,
                    "bbox": list(region),
                    "structureEngine": structure_engine,
                    "structureConfidence": structure_confidence,
                    "rows": rows,
                })
    finally:
        document.close()

    validation = validate_extracted_tables(
        all_tables,
        total_ocr_items=total_ocr_items,
        assigned_ocr_items=assigned_ocr_items,
        duplicate_rows_removed=duplicate_rows_removed,
    )
    return {
        "status": "ok" if all_tables else "no_tables",
        "analysisVersion": 2,
        "engine": "paddleocr-korean+opencv-grid+slanet-fallback",
        "renderDpi": RENDER_DPI,
        "tables": all_tables,
        "validation": validation,
        "text": "\n\n".join(
            value for value in (
                "\n\n".join(outside_blocks),
                format_tables_for_retrieval(all_tables, validation),
            ) if value
        ).strip(),
    }


def persist_pdf_table_analysis(
    data: bytes,
    result: dict[str, Any],
    assets_root: Path,
) -> dict[str, Any] | None:
    """Persist cell geometry and validation evidence as a non-embedding asset."""
    if not result.get("tables"):
        return None
    digest = hashlib.sha256(data).hexdigest()
    bundle = assets_root / "documents" / digest
    bundle.mkdir(parents=True, exist_ok=True)
    output = bundle / "pdf-tables.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validation = result.get("validation") or {}
    return {
        "kind": "attachment_pdf_table_structure",
        "filename": output.name,
        "storage_path": str(output),
        "mime_type": "application/json",
        "extracted_text": "",
        "analysis": {
            "engine": result.get("engine"),
            "status": result.get("status"),
            "validationStatus": validation.get("status"),
            "metrics": validation.get("metrics") or {},
        },
    }
