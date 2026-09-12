import io

import pymupdf
from PIL import Image

from parsers.pdf_structure import analyze_pdf_structure


def _png(width=600, height=900) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, "PNG")
    return output.getvalue()


def _scan_page(*, with_ocr: bool = False) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=600, height=900)
    page.insert_image(page.rect, stream=_png())
    if with_ocr:
        page.insert_text(
            (30, 40),
            "Invisible OCR text layer with enough characters for classification",
            render_mode=3,
        )
    result = document.tobytes()
    document.close()
    return result


def test_full_page_raster_without_text_is_scan_requiring_visual_ocr():
    result = analyze_pdf_structure(_scan_page())

    assert result["renderType"] == "raster_scan"
    assert result["textType"] == "none"
    assert result["requiresVisualOcr"] is True
    assert result["pages"][0]["fullPageRaster"] is True


def test_full_page_raster_with_text_is_ocr_layer_not_native_pdf():
    result = analyze_pdf_structure(_scan_page(with_ocr=True))

    assert result["renderType"] == "raster_scan"
    assert result["textType"] == "ocr_layer"
    assert result["requiresVisualOcr"] is True


def test_digital_text_pdf_uses_native_text():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 60), "Native digital text " * 5)
    data = document.tobytes()
    document.close()

    result = analyze_pdf_structure(data)

    assert result["renderType"] == "digital"
    assert result["textType"] == "native"
    assert result["requiresVisualOcr"] is False


def test_vector_outlined_page_is_digital_but_requires_visual_ocr():
    document = pymupdf.open()
    page = document.new_page()
    for index in range(30):
        page.draw_rect(pymupdf.Rect(20 + index, 20 + index, 80 + index, 50 + index))
    data = document.tobytes()
    document.close()

    result = analyze_pdf_structure(data)

    assert result["renderType"] == "digital"
    assert result["textType"] == "outlined"
    assert result["requiresVisualOcr"] is True


def test_scan_and_digital_pages_make_hybrid_document():
    document = pymupdf.open()
    scan = document.new_page(width=600, height=900)
    scan.insert_image(scan.rect, stream=_png())
    digital = document.new_page(width=600, height=900)
    digital.insert_text((40, 60), "Native digital text " * 5)
    data = document.tobytes()
    document.close()

    result = analyze_pdf_structure(data)

    assert result["renderType"] == "hybrid"
    assert result["rasterPageCount"] == 1
    assert result["digitalPageCount"] == 1
    assert result["requiresVisualOcr"] is True
