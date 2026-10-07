import io

import pymupdf
from PIL import Image, ImageDraw
import extractors.pdf_tables as pdf_tables

from extractors.pdf_tables import (
    detect_table_regions,
    extract_scanned_pdf_tables,
    format_tables_for_retrieval,
    rows_from_ruled_grid,
    rows_from_structure,
    split_table_region,
)


def _ruled_table(width=600, height=1200):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for x in (40, 280, 420, 560):
        draw.line((x, 40, x, height - 40), fill="black", width=3)
    for y in range(40, height - 39, 80):
        draw.line((40, y, 560, y), fill="black", width=3)
    return image


def test_ruled_table_is_detected_and_split_at_real_borders():
    image = _ruled_table()

    regions = detect_table_regions(image)

    assert len(regions) == 1
    segments = split_table_region(regions[0], image)
    assert len(segments) > 1
    assert all(segment[3] > segment[1] for segment in segments)


def test_repeated_code_boxes_are_not_mistaken_for_a_table():
    image = Image.new("RGB", (600, 500), "white")
    draw = ImageDraw.Draw(image)
    for top in (40, 160, 280):
        draw.rectangle((60, top, 540, top + 70), outline="black", width=3)
        draw.text((90, top + 20), "SELECT * FROM table", fill="black")

    assert detect_table_regions(image) == []


def test_structure_cells_receive_ocr_by_geometry():
    structure = {
        "html": "<table><tr><td></td><td></td></tr></table>",
        "boxes": [[0, 0, 100, 50], [100, 0, 200, 50]],
        "confidence": 0.95,
    }
    ocr = [
        {"id": 1, "text": "과목명", "confidence": 0.98, "bbox": [30, 40, 90, 65]},
        {"id": 2, "text": "학점", "confidence": 0.99, "bbox": [140, 40, 190, 65]},
    ]

    rows = rows_from_structure(structure, ocr, offset_x=20, offset_y=30)

    assert rows[0]["text"] == "과목명 | 학점"
    assert rows[0]["cells"][0]["bbox"] == [20.0, 30.0, 120.0, 80.0]
    assert rows[0]["cells"][1]["sourceOcrIds"] == [2]


def test_ruled_grid_keeps_separate_total_rows_and_merged_cells():
    image = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(image)
    for y in (20, 80, 140, 200, 260):
        draw.line((20, y, 580, y), fill="black", width=3)
    for x in (20, 300, 450, 580):
        draw.line((x, 20, x, 140), fill="black", width=3)
        draw.line((x, 200, x, 260), fill="black", width=3)
    for x in (20, 450, 580):
        draw.line((x, 140, x, 200), fill="black", width=3)
    ocr = [
        {"id": 1, "text": "전공합계", "confidence": .99, "bbox": [100, 155, 220, 180]},
        {"id": 2, "text": "104", "confidence": .99, "bbox": [490, 155, 540, 180]},
        {"id": 3, "text": "총계", "confidence": .99, "bbox": [100, 215, 180, 240]},
        {"id": 4, "text": "140", "confidence": .99, "bbox": [490, 215, 540, 240]},
    ]

    rows, confidence = rows_from_ruled_grid(image, (16, 16, 585, 265), ocr)

    assert [row["text"] for row in rows] == ["전공합계 | 104", "총계 | 140"]
    assert len(rows[0]["cells"]) == 2
    assert len(rows[1]["cells"]) == 3
    assert confidence > 0.5


def test_ruled_grid_restores_one_missing_regular_horizontal_rule():
    image = Image.new("RGB", (500, 330), "white")
    draw = ImageDraw.Draw(image)
    # The rule at y=140 is missing, leaving one gap exactly twice the normal row height.
    for y in (20, 80, 200, 260, 320):
        draw.line((20, y, 480, y), fill="black", width=3)
    for x in (20, 250, 480):
        draw.line((x, 20, x, 320), fill="black", width=3)
    ocr = [
        {"id": 1, "text": "HEADER", "confidence": .99, "bbox": [60, 95, 180, 125]},
        {"id": 2, "text": "FIRST", "confidence": .99, "bbox": [60, 155, 180, 185]},
    ]

    rows, _confidence = rows_from_ruled_grid(image, (16, 16, 485, 325), ocr)

    assert [row["text"] for row in rows[:2]] == ["HEADER", "FIRST"]


def test_flat_polygon_coordinates_are_supported():
    structure = {
        "html": "<table><tr><td></td></tr></table>",
        "boxes": [[0, 0, 100, 0, 100, 50, 0, 50]],
        "confidence": 0.95,
    }
    ocr = [{"id": 1, "text": "총계 140", "confidence": 0.99, "bbox": [10, 10, 90, 40]}]

    rows = rows_from_structure(structure, ocr)

    assert rows[0]["text"] == "총계 140"
    assert rows[0]["cells"][0]["bbox"] == [0.0, 0.0, 100.0, 50.0]


def test_pdf_table_retrieval_text_has_header_and_rows():
    tables = [{
        "pageNumber": 1,
        "rows": [{"text": "과목명 | 학점"}, {"text": "기본간호학 I | 2"}],
    }]

    text = format_tables_for_retrieval(tables, {"status": "passed"})

    assert "[PDF 1페이지 표 1]" in text
    assert "[표 헤더] 과목명 | 학점" in text
    assert "[행] 기본간호학 I | 2" in text


def test_scanned_pdf_table_pipeline_with_injected_backend():
    source = _ruled_table(width=600, height=400)
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    document = pymupdf.open()
    page = document.new_page(width=600, height=400)
    page.insert_image(page.rect, stream=buffer.getvalue())
    pdf = document.tobytes()
    document.close()

    class FakeBackend:
        def ocr(self, image):
            width, height = image.size
            return [
                {"id": 1, "text": "과목명", "confidence": 0.99, "bbox": [width * .2, height * .2, width * .35, height * .25]},
                {"id": 2, "text": "학점", "confidence": 0.99, "bbox": [width * .65, height * .2, width * .75, height * .25]},
            ]

        def structure(self, image):
            width, height = image.size
            return {
                "html": "<table><tr><td></td><td></td></tr></table>",
                "boxes": [[0, 0, width / 2, height], [width / 2, 0, width, height]],
                "confidence": 0.95,
            }

    structure = {
        "pages": [{"pageNumber": 1, "requiresVisualOcr": True, "renderType": "raster_scan"}],
    }
    result = extract_scanned_pdf_tables(pdf, structure, backend=FakeBackend())

    assert result["status"] == "ok"
    assert len(result["tables"]) == 1
    assert result["tables"][0]["structureEngine"] == "opencv-grid"
    assert "과목명" in result["text"]


def test_non_table_scan_does_not_load_paddle_models(monkeypatch):
    source = Image.new("RGB", (300, 400), "white")
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    page.insert_image(page.rect, stream=buffer.getvalue())
    pdf = document.tobytes()
    document.close()
    monkeypatch.setattr(
        pdf_tables,
        "_default_backend",
        lambda: (_ for _ in ()).throw(AssertionError("Paddle must stay unloaded")),
    )

    result = extract_scanned_pdf_tables(
        pdf,
        {"pages": [{"pageNumber": 1, "requiresVisualOcr": True, "renderType": "raster_scan"}]},
    )

    assert result["status"] == "no_tables"
