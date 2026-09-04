import io

from PIL import Image

import extractors.attachments as attachments


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
