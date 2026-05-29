"""학과 교육과정표 PDF → VLM 기반 범용 마크다운 표 추출.

학과별 표 양식이 다양해서 결정론 파서(pdfplumber 컬럼 매칭)는 재사용 불가 ➔
VLM이 양식 다양성을 흡수하고 [이수구분 | 과목명 | 학점 | 학년/학기] 4컬럼
마크다운 표로 통일 정규화.
"""

from __future__ import annotations

import logging
import re
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import json
import pdfplumber
from model import get_llm
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# VLM이 매 응답 첫 줄에 박아주는 입학년도 라벨 prefix.
_YEAR_RE = re.compile(r"^\s*\[YEAR:\s*(.*?)\]\s*$", re.MULTILINE)
_NO_TABLE = "[NO_TABLE]"

_HYBRID_PROMPT = """이 데이터는 대학 교육과정표 PDF에서 pdfplumber로 추출한 표 데이터(2차원 리스트) 및 페이지 텍스트다.
가로 격자선 분리 등으로 인해 하나의 과목명이 여러 행으로 쪼개졌거나(예: 'Global management'와 'case analysis' 등), 셀 병합(머지)으로 인해 빈 값("")이 다수 존재할 수 있다.

이 데이터를 철저히 해독하여 다음 형식을 정확히 지켜 마크다운 표로 정규화하여 출력하라. 다른 설명이나 코드블록(```) 금지.
1. 첫 줄: 페이지 텍스트 등에서 적용 입학년도 라벨을 감지하여 `[YEAR: <라벨>]` 형식으로 출력 (예: `[YEAR: 2025학년도 입학자부터 적용]`). 라벨을 찾을 수 없으면 `[YEAR: ]` (비움)으로 출력.
2. 두 번째 줄부터: 4컬럼 마크다운 표 출력. 헤더는 정확히:
   `| 이수구분 | 과목명 | 학점 | 학년/학기 |`
   `| --- | --- | --- | --- |`

행 작성 규칙 (반드시 준수):
- 이수구분: 표의 첫 번째 '구분' 또는 분류 열을 읽는다. 병합으로 인한 빈 칸은 상하 문맥을 파악해 '전공필수', '콜라주', '전공선택' 등으로 완벽히 forward-fill/backward-fill하여 채워 넣는다.
- 과목명: 가로선 분리로 인해 아래위 행으로 분할된 과목명(예: 'Global management'와 'case analysis')은 반드시 하나의 과목명('Global management case analysis')으로 온전히 결합해야 한다.
- 학점: 해당 과목의 취득 학점 수(예: '3', '1').
- 학년/학기: 학년 헤더(1학년, 2학년 혹은 1, 2, 3, 4 등)와 학기(1학기/2학기 혹은 1, 2, Ⅰ, Ⅱ 등)의 열 인덱스를 정확히 판독하여 '학년-학기' 형식으로 변환하여 채운다 (예: '1-1', '2-2', '3-1', '4-2').
- 소계, 합계, 편성 합계 등의 요약 통계 행은 최종 표에서 제외하라.

[페이지 상단 텍스트 컨텍스트]
{page_text}

[입력 데이터 (2차원 리스트 JSON)]
{table_json}
"""


def _split_year_prefix(response: str) -> tuple[str | None, str]:
    """VLM 응답의 `[YEAR: ...]` prefix를 떼어내 (year_label, markdown_table) 반환.
    prefix 없거나 라벨이 빈 문자열이면 year_label=None.
    """
    match = _YEAR_RE.search(response)
    if not match:
        return None, response.strip()
    label = match.group(1).strip()
    table = (response[:match.start()] + response[match.end():]).strip()
    return (label or None), table


def _is_no_table(response: str) -> bool:
    return response.strip() == _NO_TABLE


def _page_to_year(page_num: int, page_text_str: str, raw_table: list[list[str]] | None) -> dict | None:
    """페이지 텍스트와 pdfplumber 표 데이터를 LLM에 던져 year dict 1개 반환. 표 없으면 None.
    LLM 호출 실패 시 예외를 그대로 위로 던진다 (fail-fast).
    """
    if not raw_table:
        logger.info("page %d: 테이블 데이터 없음 — skip", page_num)
        return None
        
    cleaned_table = [
        ["" if cell is None else str(cell).strip() for cell in row]
        for row in raw_table
    ]
    
    table_json_str = json.dumps(cleaned_table, ensure_ascii=False, indent=2)
    prompt = _HYBRID_PROMPT.format(table_json=table_json_str, page_text=page_text_str)
    
    llm = get_llm()
    msg = HumanMessage(content=prompt)
    response = llm.invoke([msg])
    content = response.content.strip()
    
    if _is_no_table(content):
        logger.info("page %d: NO_TABLE — 커리큘럼 표 없는 페이지, skip", page_num)
        return None
        
    year_label, markdown_table = _split_year_prefix(content)
    if not markdown_table:
        logger.info("page %d: 응답에 표 본문 없음 — skip", page_num)
        return None
        
    return {
        "page_number": page_num,
        "year_label": year_label,
        "markdown_table": markdown_table,
    }


def _parse_start_year(year_label: str | None) -> int | None:
    """라벨 텍스트에서 4자리 시작 연도를 안전하게 파싱합니다."""
    if not year_label:
        return None
    nums = [int(y) for y in re.findall(r"\d{4}", year_label)]
    if not nums:
        return None
    start = nums[0]
    current_year = datetime.date.today().year
    if 2000 <= start <= current_year + 3:
        return start
    return None


def resolve_applicable_years(parsed_years: list[dict]) -> list[dict]:
    """연도 오름차순 정렬 및 종료 연도 자동 스패닝을 수행해 적용 연도 리스트와 리드 문장을 보강합니다."""
    current_year = datetime.date.today().year

    decorated = []
    for item in parsed_years:
        start = _parse_start_year(item.get("year_label"))
        decorated.append((start, item))

    valid_items = [x for x in decorated if x[0] is not None]
    invalid_items = [x for x in decorated if x[0] is None]

    valid_items.sort(key=lambda x: x[0])

    max_end_year = current_year + 1
    results = []

    for i, (start, item) in enumerate(valid_items):
        if i + 1 < len(valid_items):
            end = valid_items[i + 1][0] - 1
        else:
            end = max(start, max_end_year)

        if end < start:
            end = start

        applicable = list(range(start, end + 1))
        enumerated = ", ".join(f"{y}학년도" for y in applicable)
        lead = f"이 교육과정은 {enumerated} 입학자에게 적용됩니다."

        item["applicable_years"] = applicable
        item["lead_sentence"] = lead
        results.append(item)

    for _, item in invalid_items:
        item["applicable_years"] = []
        item["lead_sentence"] = ""
        results.append(item)

    return results


def parse(pdf_path: str | Path) -> dict:
    """PDF의 모든 페이지를 pdfplumber + LLM으로 파싱하여 입학년도별 정규화 마크다운 표를 모으고 적용 연도를 보정합니다.

    반환: {"years": [{"page_number": int, "year_label": str|None, "markdown_table": str, "applicable_years": list[int], "lead_sentence": str}]}
    실패 정책: 한 페이지라도 LLM 호출에서 예외 발생하면 즉시 raise (fail-fast).
    """
    if not Path(pdf_path).exists():
        return {"years": []}

    pages_data = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            page_text_str = page.extract_text() or ""
            tables = page.extract_tables()
            raw_table = tables[0] if tables else None
            pages_data.append((page_num, page_text_str, raw_table))

    if not pages_data:
        return {"years": []}

    # API 지연 흡수용 병렬 (Rate Limit 고려하여 max_workers=3으로 제한)
    # 한 페이지라도 예외 발생하면 list() 평가 중 raise → ingest 스크립트 abort.
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(
            lambda t: _page_to_year(t[0], t[1], t[2]),
            pages_data,
        ))

    years_data = [r for r in results if r is not None]
    resolved_years = resolve_applicable_years(years_data)
    return {"years": resolved_years}


def render_text(parsed_year: dict) -> str:
    """parse() 결과의 한 year를 RAG 본문 텍스트로 직렬화.
    적용 리드 문장과 마크다운 표를 결합해 리턴합니다.
    """
    lead = parsed_year.get("lead_sentence") or ""
    body = parsed_year.get("markdown_table") or ""
    return f"{lead}\n\n{body}".strip() if lead else body.strip()
