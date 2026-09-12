"""Deterministic PDF structure classification.

The classifier deliberately answers only questions that the PDF object graph can
support.  Semantic decisions such as "this is a useful diagram" belong to the
vision model, while scan/digital routing belongs here.
"""
from __future__ import annotations

from typing import Any

import pymupdf


FULL_PAGE_RASTER_RATIO = 0.80
MIN_TEXT_CHARS = 30
MIN_OUTLINE_PATHS = 20


def _painted_area_ratio(page: pymupdf.Page, bbox: tuple[float, float, float, float]) -> float:
    page_rect = page.rect
    painted = pymupdf.Rect(bbox) & page_rect
    page_area = max(1.0, page_rect.width * page_rect.height)
    return max(0.0, painted.width * painted.height) / page_area


def _page_structure(page: pymupdf.Page, page_number: int) -> dict[str, Any]:
    text = page.get_text("text").strip()
    try:
        bbox_log = page.get_bboxlog()
    except Exception:
        bbox_log = []

    image_boxes = [bbox for kind, bbox in bbox_log if "image" in kind]
    max_image_ratio = max(
        (_painted_area_ratio(page, bbox) for bbox in image_boxes),
        default=0.0,
    )
    path_objects = sum(1 for kind, _bbox in bbox_log if "path" in kind)
    text_chars = len(text)
    full_page_raster = max_image_ratio >= FULL_PAGE_RASTER_RATIO

    if full_page_raster:
        render_type = "raster_scan"
    elif text_chars >= MIN_TEXT_CHARS or path_objects or image_boxes:
        render_type = "digital"
    else:
        render_type = "unknown"

    if full_page_raster and text_chars >= MIN_TEXT_CHARS:
        text_type = "ocr_layer"
    elif text_chars >= MIN_TEXT_CHARS:
        text_type = "native"
    elif not full_page_raster and path_objects >= MIN_OUTLINE_PATHS:
        text_type = "outlined"
    else:
        text_type = "none"

    # Raster-origin text layers are never trusted blindly.  They may be useful as
    # a fallback, but the Forouzan and database-book fixtures demonstrate that a
    # populated OCR layer can still contain severely corrupted Korean text.
    requires_visual_ocr = render_type == "raster_scan" or text_type in {"outlined", "none"}
    return {
        "pageNumber": page_number,
        "renderType": render_type,
        "textType": text_type,
        "requiresVisualOcr": requires_visual_ocr,
        "fullPageRaster": full_page_raster,
        "largestPaintedImageRatio": round(max_image_ratio, 4),
        "textChars": text_chars,
        "paintedImageObjects": len(image_boxes),
        "imageResources": len(page.get_images(full=True)),
        "pathObjects": path_objects,
    }


def analyze_pdf_structure(data: bytes) -> dict[str, Any]:
    """Classify a PDF from its object structure, not from visual guesswork."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        pages = [_page_structure(page, index + 1) for index, page in enumerate(document)]
        if not pages:
            raise ValueError("PDF contains no pages")
    finally:
        document.close()

    raster_pages = sum(page["renderType"] == "raster_scan" for page in pages)
    digital_pages = sum(page["renderType"] == "digital" for page in pages)
    unknown_pages = len(pages) - raster_pages - digital_pages
    if raster_pages and digital_pages:
        render_type = "hybrid"
    elif raster_pages:
        render_type = "raster_scan"
    else:
        # Blank/unknown pages are operationally handled as digital rather than
        # being mistaken for scans without any raster evidence.
        render_type = "digital"

    meaningful_text_types = {
        page["textType"] for page in pages if page["textType"] != "none"
    }
    if not meaningful_text_types:
        text_type = "none"
    elif len(meaningful_text_types) == 1:
        text_type = next(iter(meaningful_text_types))
    else:
        text_type = "mixed"

    homogeneous = raster_pages in {0, len(pages)} and unknown_pages == 0
    confidence = 0.99 if homogeneous else 0.95 if unknown_pages == 0 else 0.75
    return {
        "analysisVersion": 1,
        "renderType": render_type,
        "textType": text_type,
        "requiresVisualOcr": any(page["requiresVisualOcr"] for page in pages),
        "confidence": confidence,
        "pageCount": len(pages),
        "rasterPageCount": raster_pages,
        "digitalPageCount": digital_pages,
        "unknownPageCount": unknown_pages,
        "pages": pages,
    }
