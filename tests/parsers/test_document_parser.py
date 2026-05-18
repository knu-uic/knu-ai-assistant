"""parsers/document_parser.py 회귀 테스트.

오프라인 테스트 (fixture 필요, 외부 API 불필요):
  - hwpx_bytes_to_text: sample.hwpx fixture.
  - _xlsx_to_text: sample.xlsx fixture.

라이브 테스트 (@pytest.mark.live, 외부 API/네트워크 호출):
  - _pdf_to_text_via_vlm: sample.pdf fixture + 실제 VLM API.
  - hwpx_via_preview: 공주대 게시판의 실제 synapView URL + Playwright.

활성화: pytest -m live tests/parsers/test_document_parser.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parsers.document_parser import (
    _pdf_to_text_via_vlm,
    _xlsx_to_text,
    hwpx_bytes_to_text,
    hwpx_via_preview,
)

_FIX_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "parsers"
_SAMPLE_PDF = _FIX_DIR / "sample.pdf"
_SAMPLE_XLSX = _FIX_DIR / "sample.xlsx"
_SAMPLE_HWPX = _FIX_DIR / "sample.hwpx"

# HWP synapView 라이브 테스트용 URL — 사용자가 채우는 자리.
# 예: "https://www.kongju.ac.kr/synap/synapView.do?fileSn=..."
_SYNAP_HWP_URL = ""


@pytest.mark.skipif(not _SAMPLE_XLSX.exists(), reason="sample.xlsx fixture 없음")
def test_xlsx_to_text_nonempty():
    data = _SAMPLE_XLSX.read_bytes()
    text = _xlsx_to_text(data)
    assert text, "_xlsx_to_text 결과가 비어있으면 안 됨."
    assert "[Sheet:" in text, "시트 헤더 라벨이 누락됨 (포맷 회귀)."


@pytest.mark.skipif(not _SAMPLE_HWPX.exists(), reason="sample.hwpx fixture 없음")
def test_hwpx_bytes_to_text_nonempty():
    data = _SAMPLE_HWPX.read_bytes()
    text = hwpx_bytes_to_text(data)
    assert text, "hwpx_bytes_to_text 결과가 비어있으면 안 됨."


@pytest.mark.live
@pytest.mark.skipif(not _SAMPLE_PDF.exists(), reason="sample.pdf fixture 없음")
def test_pdf_to_text_via_vlm_returns_pages():
    """실제 VLM API 호출. 비용 발생. pytest -m live 로 활성화."""
    data = _SAMPLE_PDF.read_bytes()
    text = _pdf_to_text_via_vlm(data)
    assert text, "_pdf_to_text_via_vlm 결과가 비어있으면 안 됨."
    assert "--- [Page" in text, "페이지 구분 마커가 누락됨."


@pytest.mark.live
@pytest.mark.skipif(not _SYNAP_HWP_URL, reason="_SYNAP_HWP_URL 미설정")
def test_hwp_via_synapview():
    """실제 공주대 synapView URL + Playwright Chromium launch.
    네트워크 + Playwright 의존. pytest -m live 로 활성화.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context()
            text = hwpx_via_preview(_SYNAP_HWP_URL, context)
            assert text, "synapView 결과가 비어있으면 안 됨."
        finally:
            browser.close()
