"""컴퓨터공학과 교과과정표 크롤러.

CLAUDE.md §10 결정: 정형 표는 LLM 추출 금지 → pdfplumber 결정론 경로.
1 PDF = 여러 입학년도 표. 입학년도별로 1개 record를 생성해야 RAG가
"2014학년도 입학자 기준" 같은 질문을 임베딩 유사도로 잡을 수 있다.
URL UNIQUE 제약을 우회하기 위해 fragment(#year=…)로 record를 구분.
"""

from __future__ import annotations

import re
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


def _year_url(year_label: str) -> str:
    # fragment는 서버에 전송되지 않으므로 다운로드 동작에 영향 없음.
    slug = year_label.replace(" ", "_")
    return f"{PDF_URL}#year={slug}"


def _expand_years(year_label: str) -> List[int]:
    """라벨에서 적용 연도를 모두 풀어낸다.
    "2011~2014학년도 입학자부터 적용" → [2011, 2012, 2013, 2014]
    "2017 ~ 2020학년도 입학자 적용"   → [2017, 2018, 2019, 2020]
    "2026학년도 입학자 적용"           → [2026]
    """
    rng = re.search(r"(\d{4})\s*~\s*(\d{4})", year_label)
    if rng:
        start, end = int(rng.group(1)), int(rng.group(2))
        if start <= end and end - start <= 20:  # 비정상 범위 방어
            return list(range(start, end + 1))
    return [int(y) for y in re.findall(r"\d{4}", year_label)]


def _lead_sentence(years: List[int]) -> str:
    """임베딩 검색이 '2014학년도' 같은 단일 연도 토큰을 잡도록 첫 줄에 풀어 쓴다."""
    if not years:
        return ""
    enumerated = ", ".join(f"{y}학년도" for y in years)
    return f"이 교육과정은 {enumerated} 입학자에게 적용됩니다."


def crawling(should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
    """입학년도별로 1개 record씩 반환. 교과과정표는 항상 풀 재처리이므로 should_skip 미사용."""
    pdf_path = _download_pdf()
    parsed = parse(pdf_path)
    years = parsed["years"]
    if not years:
        print(f"[{SOURCE_CODE}] PDF에서 추출된 연도가 없습니다.")
        return []

    records: List[dict] = []
    for year in years:
        year_label = year.get("year_label") or f"page-{year.get('page_number')}"
        applicable = _expand_years(year_label)
        lead = _lead_sentence(applicable)
        body = render_text(year)
        content = f"{lead}\n\n{body}" if lead else body
        title = f"{SOURCE_NAME} ({year_label})"
        url = _year_url(year_label)
        keywords = ["교육과정", "전공", "학점"] + [f"{y}학년도" for y in applicable]
        records.append({
            "title": title,
            "date": "",
            "content": content,
            "url": url,
            "assets": [],
            "pre_refined": True,
            "metadata": {
                "title": title,
                "content": content,
                "target": [DEPARTMENT],
                "start_date": None,
                "end_date": None,
                "category": "학사/수업",
                "keywords": keywords,
                "url": url,
            },
            "extra": {
                "curriculum": {"years": [year]},
                "page_url": PAGE_URL,
                "applicable_years": applicable,
            },
        })

    labels = [y.get("year_label") for y in years]
    print(f"[{SOURCE_CODE}] {len(records)}개 연도 record 생성: {labels}")
    return records
