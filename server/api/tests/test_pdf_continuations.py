import io

import pymupdf
from PIL import Image, ImageDraw

from extractors.pdf_continuations import _pair_candidate, detect_pdf_continuations


def _page_image(*, first: bool) -> Image.Image:
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    if first:
        draw.rectangle((90, 570, 510, 760), fill=(225, 228, 232))
        for index, number in enumerate(range(8, 14)):
            draw.text((110, 590 + index * 25), f"{number} SELECT sharedName", fill="black")
    else:
        draw.rectangle((85, 45, 515, 255), fill=(225, 228, 232))
        for index, number in enumerate(range(14, 20)):
            draw.text((105, 65 + index * 25), f"{number} SELECT sharedName", fill="black")
    return image


def test_pair_candidate_recognizes_sequential_code(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=600, height=800)
    document.new_page(width=600, height=800)
    previous_page, next_page = document[0], document[1]
    monkeypatch.setattr(previous_page, "get_textbox", lambda _rect: "8 SELECT sharedName\n13 WHERE sharedName")
    monkeypatch.setattr(next_page, "get_textbox", lambda _rect: "14 ELSE sharedName\n19 END sharedName")

    result = _pair_candidate(
        _page_image(first=True), _page_image(first=False), previous_page, next_page,
    )

    assert result is not None
    assert result["kind"] == "code"
    assert result["evidence"]["sequentialLineNumbers"] is True
    document.close()


def test_unrelated_page_blocks_are_not_joined(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=600, height=800)
    document.new_page(width=600, height=800)
    previous_page, next_page = document[0], document[1]
    monkeypatch.setattr(previous_page, "get_textbox", lambda _rect: "unrelated alpha")
    monkeypatch.setattr(next_page, "get_textbox", lambda _rect: "different beta")

    result = _pair_candidate(
        _page_image(first=True), _page_image(first=False), previous_page, next_page,
    )

    assert result is None
    document.close()


def test_sequential_numbers_without_shared_object_identity_are_not_joined(monkeypatch):
    document = pymupdf.open()
    document.new_page(width=600, height=800)
    document.new_page(width=600, height=800)
    previous_page, next_page = document[0], document[1]
    monkeypatch.setattr(previous_page, "get_textbox", lambda _rect: "13 previous chapter")
    monkeypatch.setattr(next_page, "get_textbox", lambda _rect: "14 unrelated section")

    result = _pair_candidate(
        _page_image(first=True), _page_image(first=False), previous_page, next_page,
    )

    assert result is None
    document.close()


def test_detected_continuation_has_page_span_and_stitched_png():
    document = pymupdf.open()
    for first in (True, False):
        page = document.new_page(width=600, height=800)
        output = io.BytesIO()
        _page_image(first=first).save(output, "PNG")
        page.insert_image(page.rect, stream=output.getvalue())
        text = "8 SELECT sharedName\n13 WHERE sharedName" if first else "14 ELSE sharedName\n19 END sharedName"
        page.insert_text((100, 600 if first else 80), text, fontsize=10, render_mode=3)
    data = document.tobytes()
    document.close()
    result = detect_pdf_continuations(data, {
        "pages": [
            {"pageNumber": 1, "renderType": "raster_scan"},
            {"pageNumber": 2, "renderType": "raster_scan"},
        ],
    })

    assert len(result) == 1
    assert result[0]["pageSpan"] == [1, 2]
    assert result[0]["imageData"].startswith(b"\x89PNG")
