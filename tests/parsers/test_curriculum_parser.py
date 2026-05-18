"""parsers/curriculum_parser.py 회귀 테스트.

전략:
- Mock 단위 테스트: image_to_text/convert_from_path 를 monkeypatch 해서 VLM API 호출 없이
  파서 흐름(prefix split, NO_TABLE 필터, fail-fast) 검증. 항상 실행.
- Live 통합 테스트(@pytest.mark.live): tests/fixtures/parsers/sample_curriculum.pdf 가
  있고 OPENAI_API_KEY 가 세팅돼 있으면 실제 VLM 호출. 옵트인.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from parsers.curriculum_parser import (
    _is_no_table,
    _split_year_prefix,
    parse,
    render_text,
)

_FIXTURE_PDF = Path(__file__).resolve().parent.parent / "fixtures" / "parsers" / "sample_curriculum.pdf"


# ── _split_year_prefix ────────────────────────────────────────────────────

def test_split_year_prefix_extracts_label():
    resp = (
        "[YEAR: 2014학년도 입학자 적용]\n"
        "| 이수구분 | 과목명 | 학점 | 학년/학기 |\n"
        "| --- | --- | --- | --- |\n"
        "| 전공필수 | 데이터구조 | 3 | 2-Ⅰ |"
    )
    label, table = _split_year_prefix(resp)
    assert label == "2014학년도 입학자 적용"
    assert table.startswith("| 이수구분 |")
    assert "데이터구조" in table


def test_split_year_prefix_empty_label_returns_none():
    resp = "[YEAR: ]\n| 이수구분 | 과목명 | 학점 | 학년/학기 |\n| --- | --- | --- | --- |\n| 전공 | A | 3 | 1-Ⅰ |"
    label, table = _split_year_prefix(resp)
    assert label is None
    assert table.startswith("| 이수구분 |")


def test_split_year_prefix_missing_prefix_returns_none():
    resp = "| 이수구분 | 과목명 | 학점 | 학년/학기 |\n| --- | --- | --- | --- |\n| 전공 | A | 3 | 1-Ⅰ |"
    label, table = _split_year_prefix(resp)
    assert label is None
    assert table == resp.strip()


# ── _is_no_table ─────────────────────────────────────────────────────────

def test_is_no_table_detects_marker():
    assert _is_no_table("[NO_TABLE]") is True
    assert _is_no_table("  [NO_TABLE]  \n") is True


def test_is_no_table_rejects_other_responses():
    assert _is_no_table("[YEAR: 2014]\n| ... |") is False
    assert _is_no_table("") is False
    assert _is_no_table("[YEAR: ]") is False


# ── render_text (pass-through) ───────────────────────────────────────────

def test_render_text_returns_markdown_table_verbatim():
    year = {
        "page_number": 3,
        "year_label": "2018학년도 입학자 적용",
        "markdown_table": "| 이수구분 |\n| --- |\n| 전공필수 |",
    }
    assert render_text(year) == year["markdown_table"]


# ── parse() — mock based ─────────────────────────────────────────────────

class _FakePILImage:
    """page_image.save(buf, format="PNG") 만 호출되므로 그것만 흉내."""
    def save(self, buf, format="PNG"):
        buf.write(b"\x89PNG\r\n\x1a\nfake")


def test_parse_filters_no_table_pages(monkeypatch, tmp_path):
    responses = iter([
        "[YEAR: 2014학년도 입학자 적용]\n"
        "| 이수구분 | 과목명 | 학점 | 학년/학기 |\n"
        "| --- | --- | --- | --- |\n"
        "| 전공필수 | 데이터구조 | 3 | 2-Ⅰ |",
        "[NO_TABLE]",
        "[YEAR: 2015학년도 입학자 적용]\n"
        "| 이수구분 | 과목명 | 학점 | 학년/학기 |\n"
        "| --- | --- | --- | --- |\n"
        "| 전공필수 | 알고리즘 | 3 | 3-Ⅰ |",
    ])
    monkeypatch.setattr(
        "parsers.curriculum_parser.image_to_text",
        lambda *a, **k: next(responses),
    )
    monkeypatch.setattr(
        "pdf2image.convert_from_path",
        lambda *a, **k: [_FakePILImage(), _FakePILImage(), _FakePILImage()],
    )

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    result = parse(fake_pdf)

    # NO_TABLE 페이지(2번째)는 누락.
    assert len(result["years"]) == 2
    labels = [y["year_label"] for y in result["years"]]
    assert "2014학년도 입학자 적용" in labels
    assert "2015학년도 입학자 적용" in labels
    # 각 year 에 markdown_table 존재.
    for y in result["years"]:
        assert y["markdown_table"].startswith("| 이수구분 |")
        assert "page_number" in y


def test_parse_fails_fast_on_vlm_exception(monkeypatch, tmp_path):
    """페이지 한 장이라도 VLM 호출에서 예외가 나면 그대로 raise (부분 적재 금지)."""
    def _boom(*a, **k):
        raise RuntimeError("VLM 호출 실패")

    monkeypatch.setattr("parsers.curriculum_parser.image_to_text", _boom)
    monkeypatch.setattr(
        "pdf2image.convert_from_path",
        lambda *a, **k: [_FakePILImage(), _FakePILImage()],
    )

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    with pytest.raises(RuntimeError, match="VLM 호출 실패"):
        parse(fake_pdf)


def test_parse_empty_pdf_returns_no_years(monkeypatch, tmp_path):
    monkeypatch.setattr("pdf2image.convert_from_path", lambda *a, **k: [])
    fake_pdf = tmp_path / "empty.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 stub")

    assert parse(fake_pdf) == {"years": []}


# ── Live 통합 테스트 ─────────────────────────────────────────────────────

_LIVE_SKIP_REASON = (
    "fixture 또는 OPENAI_API_KEY 누락. "
    "tests/fixtures/parsers/sample_curriculum.pdf 드롭 후 OPENAI_API_KEY 설정 시 활성화."
)


@pytest.mark.live
@pytest.mark.skipif(
    not _FIXTURE_PDF.exists() or not os.getenv("OPENAI_API_KEY"),
    reason=_LIVE_SKIP_REASON,
)
def test_live_parse_returns_normalized_markdown():
    result = parse(_FIXTURE_PDF)
    assert result["years"], "fixture PDF에서 최소 1개 년도가 추출되어야 한다."

    first = result["years"][0]
    assert "page_number" in first
    assert "year_label" in first
    assert "markdown_table" in first

    table = first["markdown_table"]
    # 헤더가 약속한 4컬럼 정확히 포함.
    assert "| 이수구분" in table
    assert "| 과목명" in table
    assert "| 학점" in table
    assert "| 학년/학기" in table
    # 표 구분선 + 데이터 행 1개 이상 (총 3 라인 이상).
    assert len([ln for ln in table.splitlines() if ln.strip().startswith("|")]) >= 3
