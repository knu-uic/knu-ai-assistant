import io
import json

from PIL import Image
import pytest

import extractors.attachments as attachments
from model import ImageOutputTruncated, ImageAnalysisTimeout


def test_tiny_inline_ui_image_is_ignored_before_vlm(monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(output, "PNG")
    monkeypatch.setattr(attachments, "_download", lambda url, context: output.getvalue())
    monkeypatch.setattr(
        attachments,
        "_hwp_image_analysis",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tiny image must not call VLM")),
    )

    text, raw, mime, analysis = attachments.inline_image_to_text(
        "https://example.test/icon.png", object(), "공지 문맥", "[본문 그림 1]",
    )

    assert text == ""
    assert raw is None
    assert mime is None
    assert analysis["status"] == "ignored_small_ui_image"


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize("error", [ImageOutputTruncated("token limit"), ImageAnalysisTimeout("deadline")])
def test_failed_inline_analysis_preserves_original_without_search_text(monkeypatch, error):
    data = image_bytes()
    monkeypatch.setattr(attachments, "_download", lambda *args: data)

    def fail(*args):
        raise error

    monkeypatch.setattr(attachments, "_image_to_text", fail)
    text, raw, mime, analysis = attachments.inline_image_to_text("https://example.test/poster.png", object())
    assert text == analysis["searchText"] == ""
    assert raw == data
    assert mime == "image/png"
    assert analysis["status"] == "failed"
    assert analysis["requiresReview"] is True


@pytest.mark.parametrize("raw", ['{"ocrText":"partial', "not JSON", "{}", '{"ocrText":[],"description":"bad"}'])
def test_broken_analysis_is_not_indexed_as_description(monkeypatch, raw):
    data = image_bytes()
    monkeypatch.setattr(attachments, "_download", lambda *args: data)
    monkeypatch.setattr(attachments, "_image_to_text", lambda *args: raw)
    text, original, _, analysis = attachments.inline_image_to_text("https://example.test/poster.png", object())
    assert text == ""
    assert original == data
    assert analysis["status"] == "failed"


def test_complete_analysis_still_indexes_ocr_and_description(monkeypatch):
    monkeypatch.setattr(attachments, "_download", lambda *args: image_bytes())
    monkeypatch.setattr(attachments, "_image_to_text", lambda *args: json.dumps({
        "kind": "table_image", "ocrText": "16일 교육 10:00", "description": "10월 일정표",
        "contextMatch": "supports", "confidence": 0.8,
    }))
    text, original, _, analysis = attachments.inline_image_to_text("https://example.test/poster.png", object())
    assert text == "16일 교육 10:00\n10월 일정표"
    assert original
    assert analysis["status"] == "complete"


def test_failed_attachment_image_keeps_original_for_review(monkeypatch):
    data = image_bytes()
    monkeypatch.setattr(attachments, "_download", lambda *args: data)

    def fail(*args):
        raise ImageOutputTruncated("token limit")

    monkeypatch.setattr(attachments, "_image_to_text", fail)
    text, meta = attachments.attachment_to_text({
        "filename": "calendar.png", "download_url": "https://example.test/calendar.png",
    }, object())
    assert meta["raw_bytes"] == data
    assert meta["extracted_text"] == ""
    assert meta["review_required"] is True
    assert "원본 보존" in text
