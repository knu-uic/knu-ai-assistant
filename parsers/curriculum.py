"""학과 교육과정표 PDF → VLM 기반 범용 마크다운 표 추출.

학과별 표 양식이 다양해서 결정론 파서(pdfplumber 컬럼 매칭)는 재사용 불가 ➔
VLM이 양식 다양성을 흡수하고 [이수구분 | 과목명 | 학점 | 학년/학기] 4컬럼
마크다운 표로 통일 정규화.
"""

from __future__ import annotations

import io
import logging
import re
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from model import LLM_MODEL, image_to_text

logger = logging.getLogger(__name__)

# VLM이 매 응답 첫 줄에 박아주는 입학년도 라벨 prefix.
_YEAR_RE = re.compile(r"^\s*\[YEAR:\s*(.*?)\]\s*$", re.MULTILINE)
_NO_TABLE = "[NO_TABLE]"

_PROMPT = """이 이미지는 대학 학과의 교육과정표(커리큘럼) 한 페이지다.
다음 형식을 정확히 지켜 응답하라. 다른 설명·코드 블록(```) 금지.
1. 첫 줄: 페이지에 적힌 입학년도 라벨을 `[YEAR: <라벨>]` 형식으로 출력.
   (예: `[YEAR: 2014학년도 입학자 적용]`). 라벨 없으면 `[YEAR: ]` (값 비움).
2. 두 번째 줄부터: 강좌를 4컬럼 마크다운 표로 출력. 헤더 행은 정확히:
   `| 이수구분 | 과목명 | 학점 | 학년/학기 |`
   `| --- | --- | --- | --- |`
3. 행 규칙 (반드시 준수):
   - 한 강좌가 여러 학기에 개설되면 학기별로 행 분리 (1 row = 1 (과목 × 학기) 개설).
   - 이수구분: 표의 첫 번째 '구분' 열(전공필수/전공선택/교양 등)을 채운다.
     * 중요: 셀이 상하로 크게 병합되어 있는 경우, "전공선택" 같은 텍스트가 셀의 맨 아래나 구석에 치우쳐 적혀 있더라도, 해당 병합 범위 전체에 속하는 모든 과목들의 이수구분을 동일하게 "전공선택"으로 채워 넣어야 한다.
   - 학점: 그 과목의 학점.
   - 학년/학기: 표가 매트릭스(행렬) 형태로 되어 있어 학년/학기가 '열 제목(Header)'에 있다면, 학점이나 동그라미(O)가 표기된 교차점을 읽고 해당 열의 학년/학기를 반드시 논리적으로 채워 넣는다 (예: "1-1", "2학년 2학기" 등 표의 맥락을 살려서 기재). 절대 빈칸으로 두지 말 것.
4. 누락 방지: 표에 적힌 모든 과목들을 위에서부터 차례대로 하나도 빠짐없이 표에 정리하라.
5. 커리큘럼 표가 없는 페이지(표지·목차·부록 등): `[NO_TABLE]` 만 한 줄로 출력."""


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


def _page_to_year(page_num: int, page_image) -> dict | None:
    """페이지 이미지 1장을 VLM에 던져 year dict 1개 반환. 표 없으면 None.
    VLM 호출 실패 시 예외를 그대로 위로 던진다 (fail-fast).
    """
    png_buffer = io.BytesIO()
    page_image.save(png_buffer, format="PNG")
    response = image_to_text(
        png_buffer.getvalue(), "image/png", _PROMPT, model=LLM_MODEL
    )
    if _is_no_table(response):
        logger.info("page %d: NO_TABLE — 커리큘럼 표 없는 페이지, skip", page_num)
        return None
    year_label, markdown_table = _split_year_prefix(response)
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
    """PDF의 모든 페이지를 VLM에 던져 입학년도별 정규화 마크다운 표를 모으고 적용 연도를 보정합니다.

    반환: {"years": [{"page_number": int, "year_label": str|None, "markdown_table": str, "applicable_years": list[int], "lead_sentence": str}]}
    실패 정책: 한 페이지라도 VLM 호출에서 예외 발생하면 즉시 raise (fail-fast).
    """
    from pdf2image import convert_from_path

    pages = convert_from_path(str(pdf_path), dpi=600)
    if not pages:
        return {"years": []}

    # API 지연 흡수용 병렬 (rate limit 고려 5 workers).
    # 한 페이지라도 예외 발생하면 list() 평가 중 raise → ingest 스크립트 abort.
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(
            lambda t: _page_to_year(*t),
            enumerate(pages, start=1),
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
