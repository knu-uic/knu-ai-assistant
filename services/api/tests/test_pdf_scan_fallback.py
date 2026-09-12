import pymupdf

import extractors.attachments as attachments


def test_scanned_pdf_fallback_renders_with_bundled_pymupdf(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=200, height=100)
    pdf = document.tobytes()
    document.close()

    seen = []
    monkeypatch.setattr(
        attachments,
        "pdf_to_text",
        lambda _data: (_ for _ in ()).throw(AssertionError("image-only scan must skip ODL")),
    )
    monkeypatch.setattr(
        attachments,
        "_image_to_text",
        lambda data, mime: seen.append((data, mime)) or "OCR result",
    )

    assert attachments._pdf_bytes_full(pdf) == "[PDF 1페이지]\nOCR result"
    assert len(seen) == 1
    assert seen[0][0].startswith(b"\x89PNG\r\n\x1a\n")
    assert seen[0][1] == "image/png"


def test_scanned_pdf_does_not_trust_populated_ocr_layer(monkeypatch):
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 900), False)
    image.clear_with(255)
    document = pymupdf.open()
    page = document.new_page(width=600, height=900)
    page.insert_image(page.rect, pixmap=image)
    page.insert_text(
        (30, 40),
        "Corrupted OCR layer that should not bypass visual OCR processing",
        render_mode=3,
    )
    pdf = document.tobytes()
    document.close()

    monkeypatch.setattr(attachments, "pdf_to_text", lambda _data: "broken OCR text")
    monkeypatch.setattr(attachments, "_image_to_text", lambda *_args: "visual OCR text")

    result = attachments._pdf_bytes_full(pdf)
    assert "visual OCR text" in result
    assert "broken OCR text" not in result


def test_structured_table_text_bypasses_page_vlm(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=200, height=100)
    pdf = document.tobytes()
    document.close()

    monkeypatch.setattr(
        attachments,
        "_image_to_text",
        lambda *_args: (_ for _ in ()).throw(AssertionError("table result must bypass page VLM")),
    )

    result = attachments._pdf_bytes_full(
        pdf,
        table_analysis={
            "text": "[PDF 1페이지 표 1]\n[행] 기본간호학 I | 2",
            "tables": [{"pageNumber": 1}],
        },
    )

    assert result == "[PDF 1페이지 표 1]\n[행] 기본간호학 I | 2"


def test_table_page_does_not_hide_other_scan_pages(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=200, height=100)
    document.new_page(width=200, height=100)
    pdf = document.tobytes()
    document.close()

    seen = []
    monkeypatch.setattr(
        attachments,
        "_image_to_text",
        lambda _data, _mime: seen.append(True) or "second page OCR",
    )

    result = attachments._pdf_bytes_full(
        pdf,
        table_analysis={
            "text": "[PDF 1페이지 표 1]\n[행] A | B",
            "tables": [{"pageNumber": 1}],
        },
    )

    assert result == "[PDF 1페이지 표 1]\n[행] A | B\n\n[PDF 2페이지]\nsecond page OCR"
    assert len(seen) == 1
