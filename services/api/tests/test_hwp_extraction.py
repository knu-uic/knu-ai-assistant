import struct
from extractors.attachments import _hwp_record_stream_text
from extractors.hwp_structured import _counter_f1


def _record(tag_id: int, payload: bytes) -> bytes:
    header = tag_id | (len(payload) << 20)
    return struct.pack("<I", header) + payload


def test_hwp_record_stream_extracts_paragraph_text_and_skips_controls():
    # tab control은 8 UTF-16 units이고 나머지 7개 payload는 본문으로 읽으면 안 된다.
    tab_control = [9, 0xAC00, 0xB098, 0, 0, 0, 0, 0]
    units = [ord("공"), ord("주"), *tab_control, ord("대"), ord("학"), 13, ord("요"), ord("람")]
    paragraph = struct.pack(f"<{len(units)}H", *units)
    stream = _record(66, b"ignored") + _record(67, paragraph)

    assert _hwp_record_stream_text(stream) == "공주 대학\n요람"


def test_hwp_record_stream_combines_utf16_surrogate_pairs():
    payload = "학교 U0001F3EB".encode("utf-16le")

    assert _hwp_record_stream_text(_record(67, payload)) == "학교 U0001F3EB"


def test_cross_parser_score_ignores_spacing_but_detects_missing_content():
    complete = "2026학년도 장학금 신청 기간 9월 1일 문의 학생복지과"
    spacing_only = "2026학년도   장학금\n신청 기간 9월 1일 문의 학생복지과"
    missing = "2026학년도 장학금"

    assert _counter_f1(complete, spacing_only) == 1.0
    assert _counter_f1(complete, missing) < _counter_f1(complete, spacing_only)
