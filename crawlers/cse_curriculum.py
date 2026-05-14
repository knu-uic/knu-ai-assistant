"""컴퓨터공학과 교과과정표 크롤러.

CLAUDE.md §10 결정: 정형 표는 LLM 추출 금지 → pdfplumber 결정론 경로.
1 PDF에 7개 연도 표 → JSONB extra.curriculum.years[]에 전체 보존,
content/임베딩은 최신 연도(2026)만 사람이 읽기 좋게 렌더.
"""

from __future__ import annotations

import ssl
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from curriculum_parser import parse, render_text

SOURCE_CODE = "cse_curriculum"
SOURCE_NAME = "컴퓨터공학과 교과과정표"
DEPARTMENT = "컴퓨터공학과"
KIND = "academic"
BASE_URL = "https://computer.kongju.ac.kr"

PDF_URL = "https://computer.kongju.ac.kr/documentViewer/ZD1140/251/1261/fileDown.do"
PAGE_URL = "https://computer.kongju.ac.kr/ZD1140/11579/subview.do"
CACHE_DIR = Path("crawl_result/cse_curriculum")


def _download_pdf() -> Path:
    # computer.kongju.ac.kr가 옛 TLS만 받음 → SECLEVEL=1로 핸드셰이크 가능.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / "curriculum.pdf"
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        out.write_bytes(resp.read())
    return out


def crawling(should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """should_skip은 시그니처 통일을 위해 받지만 사용하지 않음.
    교과과정표는 항상 최신 버전을 갱신해야 하므로 매번 풀 재처리.
    """
    pdf_path = _download_pdf()
    parsed = parse(pdf_path)
    years = parsed["years"]
    if not years:
        print(f"[{SOURCE_CODE}] PDF에서 추출된 연도가 없습니다.")
        return []

    latest = years[-1]
    content = render_text(latest)
    title = f"{SOURCE_NAME} ({latest.get('year_label') or '최신'})"
    print(f"[{SOURCE_CODE}] 7개 연도 파싱 완료. 최신: {latest.get('year_label')}")

    record = {
        "title": title,
        "date": "",
        "content": content,
        "url": PDF_URL,
        "assets": [],
        "pre_refined": True,
        "metadata": {
            "title": title,
            "content": content,
            "target": [DEPARTMENT],
            "start_date": None,
            "end_date": None,
            "category": "학사/수업",
            "keywords": ["교육과정", "전공", "학점"],
            "url": PDF_URL,
        },
        "extra": {
            "curriculum": parsed,
            "page_url": PAGE_URL,
        },
    }
    return [record]
