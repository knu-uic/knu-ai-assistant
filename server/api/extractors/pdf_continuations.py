"""Detect visual objects that continue across adjacent PDF pages."""
from __future__ import annotations

import io
import re
from typing import Any

import pymupdf
from PIL import Image


DETECT_DPI = 54
STITCH_DPI = 150


def _visual_blocks(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Find large filled/illustrated blocks while ignoring ordinary text lines."""
    import cv2
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (0, 0), max(3.0, width / 180))
    paper = float(np.percentile(gray, 90))
    mask = (blur < paper - 7).astype("uint8") * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(5, width // 80), max(5, height // 120))
        ),
    )
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(3, width // 150), max(3, height // 180))
        ),
    )
    boxes = []
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area_ratio = box_width * box_height / max(1, width * height)
        if area_ratio < 0.01 or box_width < width * 0.25 or box_height < height * 0.04:
            continue
        boxes.append((x, y, x + box_width, y + box_height))
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def _normalized_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> list[float]:
    width, height = size
    return [
        round(box[0] / width, 5), round(box[1] / height, 5),
        round(box[2] / width, 5), round(box[3] / height, 5),
    ]


def _page_rect(box: tuple[int, int, int, int], image: Image.Image, page: pymupdf.Page) -> pymupdf.Rect:
    scale_x = page.rect.width / image.width
    scale_y = page.rect.height / image.height
    return pymupdf.Rect(
        box[0] * scale_x, box[1] * scale_y, box[2] * scale_x, box[3] * scale_y,
    )


def _line_numbers(text: str) -> list[int]:
    return [
        int(value)
        for value in re.findall(r"(?m)^\s*(\d{1,4})(?=\s|$)", text or "")
    ]


def _shared_identifiers(left: str, right: str) -> list[str]:
    pattern = r"[A-Za-z_][A-Za-z0-9_]{4,}"
    left_values = {value.lower() for value in re.findall(pattern, left or "")}
    right_values = {value.lower() for value in re.findall(pattern, right or "")}
    return sorted(left_values & right_values)


def _vertical_signature(image: Image.Image, box: tuple[int, int, int, int]) -> list[float]:
    import cv2
    import numpy as np

    crop = np.asarray(image.crop(box).convert("L"))
    height, width = crop.shape
    binary = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, height // 4))),
    )
    counts = np.count_nonzero(vertical, axis=0)
    indices = np.flatnonzero(counts >= max(8, int(height * 0.35))).tolist()
    centers = []
    for value in indices:
        if not centers or value - centers[-1][-1] > 1:
            centers.append([value])
        else:
            centers[-1].append(value)
    return [round(sum(group) / len(group) / max(1, width), 3) for group in centers]


def _matching_verticals(left: list[float], right: list[float]) -> int:
    used: set[int] = set()
    matches = 0
    for value in left:
        choices = [
            (abs(value - other), index)
            for index, other in enumerate(right)
            if index not in used and abs(value - other) <= 0.035
        ]
        if choices:
            _distance, index = min(choices)
            used.add(index)
            matches += 1
    return matches


def _pair_candidate(
    previous_image: Image.Image,
    next_image: Image.Image,
    previous_page: pymupdf.Page,
    next_page: pymupdf.Page,
) -> dict[str, Any] | None:
    previous_blocks = [
        box for box in _visual_blocks(previous_image)
        if box[3] >= previous_image.height * 0.76
    ]
    next_blocks = [
        box for box in _visual_blocks(next_image)
        if box[1] <= next_image.height * 0.24
    ]
    if not previous_blocks or not next_blocks:
        return None
    previous_box = max(previous_blocks, key=lambda box: box[3])
    next_box = min(next_blocks, key=lambda box: box[1])
    previous_normalized = _normalized_box(previous_box, previous_image.size)
    next_normalized = _normalized_box(next_box, next_image.size)
    previous_width = previous_normalized[2] - previous_normalized[0]
    next_width = next_normalized[2] - next_normalized[0]
    overlap = max(0.0, min(previous_normalized[2], next_normalized[2]) - max(previous_normalized[0], next_normalized[0]))
    overlap_ratio = overlap / max(0.001, min(previous_width, next_width))
    width_ratio = previous_width / max(0.001, next_width)
    if overlap_ratio < 0.72 or not 0.72 <= width_ratio <= 1.38:
        return None

    previous_text = previous_page.get_textbox(
        _page_rect(previous_box, previous_image, previous_page)
    ).strip()
    next_text = next_page.get_textbox(
        _page_rect(next_box, next_image, next_page)
    ).strip()
    previous_numbers = _line_numbers(previous_text)
    next_numbers = _line_numbers(next_text)
    sequential = bool(
        previous_numbers and next_numbers
        and previous_numbers[-1] + 1 == next_numbers[0]
    )
    shared = _shared_identifiers(previous_text, next_text)
    vertical_matches = _matching_verticals(
        _vertical_signature(previous_image, previous_box),
        _vertical_signature(next_image, next_box),
    )
    # Repeated domain words occur on many consecutive textbook pages and are
    # supporting evidence only. Auto-join requires an ordered sequence or an
    # independently matching table grid; ambiguous pairs stay separate.
    sequential_confirmed = sequential and bool(shared)
    grid_confirmed = vertical_matches >= 3 and len(shared) >= 3
    if not sequential_confirmed and not grid_confirmed:
        return None
    kind = "code" if sequential_confirmed else "table"
    return {
        "kind": kind,
        "confidence": 0.98 if sequential_confirmed else 0.92,
        "previousBox": previous_normalized,
        "nextBox": next_normalized,
        "previousText": previous_text,
        "nextText": next_text,
        "evidence": {
            "sequentialLineNumbers": sequential,
            "sharedIdentifiers": shared[:12],
            "matchingVerticalRules": vertical_matches,
            "horizontalOverlapRatio": round(overlap_ratio, 4),
            "widthRatio": round(width_ratio, 4),
        },
    }


def _pixel_box(normalized: list[float], image: Image.Image) -> tuple[int, int, int, int]:
    return (
        max(0, round(normalized[0] * image.width)),
        max(0, round(normalized[1] * image.height)),
        min(image.width, round(normalized[2] * image.width)),
        min(image.height, round(normalized[3] * image.height)),
    )


def _stitched_image(
    previous: Image.Image, next_image: Image.Image,
    previous_box: list[float], next_box: list[float],
) -> bytes:
    first = previous.crop(_pixel_box(previous_box, previous)).convert("RGB")
    second = next_image.crop(_pixel_box(next_box, next_image)).convert("RGB")
    target_width = max(first.width, second.width)
    separator = 18
    canvas = Image.new("RGB", (target_width, first.height + separator + second.height), "white")
    canvas.paste(first, ((target_width - first.width) // 2, 0))
    canvas.paste(second, ((target_width - second.width) // 2, first.height + separator))
    from PIL import ImageDraw
    ImageDraw.Draw(canvas).rectangle(
        (0, first.height + 7, target_width, first.height + 10), fill=(100, 100, 100)
    )
    output = io.BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return output.getvalue()


def continuation_from_page_pair(
    previous_image: Image.Image,
    next_image: Image.Image,
    previous_page: pymupdf.Page,
    next_page: pymupdf.Page,
    previous_page_number: int,
    next_page_number: int,
) -> dict[str, Any] | None:
    """Detect and materialize one pair when page renders already exist."""
    candidate = _pair_candidate(
        previous_image, next_image, previous_page, next_page,
    )
    if candidate is None:
        return None
    candidate["pageSpan"] = [previous_page_number, next_page_number]
    candidate["segments"] = [
        {"pageNumber": previous_page_number, "bboxNormalized": candidate.pop("previousBox")},
        {"pageNumber": next_page_number, "bboxNormalized": candidate.pop("nextBox")},
    ]
    candidate["imageData"] = _stitched_image(
        previous_image, next_image,
        candidate["segments"][0]["bboxNormalized"],
        candidate["segments"][1]["bboxNormalized"],
    )
    return candidate


def detect_pdf_continuations(
    data: bytes,
    pdf_structure: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return high-confidence adjacent-page continuations with stitched PNGs."""
    pages_by_number = {
        int(page["pageNumber"]): page for page in pdf_structure.get("pages") or []
    }
    document = pymupdf.open(stream=data, filetype="pdf")
    detect_matrix = pymupdf.Matrix(DETECT_DPI / 72, DETECT_DPI / 72)
    stitch_matrix = pymupdf.Matrix(STITCH_DPI / 72, STITCH_DPI / 72)
    continuations = []
    try:
        previous_image: Image.Image | None = None
        previous_page: pymupdf.Page | None = None
        for page_index in range(len(document)):
            page_number = page_index + 1
            page_info = pages_by_number.get(page_number, {})
            if page_info.get("renderType") != "raster_scan":
                previous_image = None
                previous_page = None
                continue
            page = document[page_index]
            pixmap = page.get_pixmap(matrix=detect_matrix, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            if previous_image is not None and previous_page is not None:
                candidate = _pair_candidate(
                    previous_image, image, previous_page, page,
                )
                if candidate:
                    high_previous = Image.open(io.BytesIO(
                        previous_page.get_pixmap(matrix=stitch_matrix, alpha=False).tobytes("png")
                    )).convert("RGB")
                    high_next = Image.open(io.BytesIO(
                        page.get_pixmap(matrix=stitch_matrix, alpha=False).tobytes("png")
                    )).convert("RGB")
                    candidate = continuation_from_page_pair(
                        high_previous, high_next, previous_page, page,
                        page_number - 1, page_number,
                    )
                    if candidate:
                        continuations.append(candidate)
            previous_image = image
            previous_page = page
    finally:
        document.close()
    return continuations
