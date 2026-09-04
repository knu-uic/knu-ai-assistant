from extractors.attachments import _decode_image_analysis_json


def test_repairs_fenced_small_model_json_with_invalid_korean_escape():
    raw = r'''```json
{"kind":"table_image","ocrText":"필요 사항을\공지하고 동의여부가\정시됩니다.","description":"포털 동의 화면","contextMatch":"supports","confidence":0.95,}
```'''

    value = _decode_image_analysis_json(raw)

    assert value is not None
    assert value["kind"] == "table_image"
    assert value["ocrText"] == "필요 사항을공지하고 동의여부가정시됩니다."
    assert value["description"] == "포털 동의 화면"
