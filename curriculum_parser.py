"""학과 교육과정표 PDF (pdfplumber.extract_tables() 출력) 정형 변환.

CLAUDE.md §10 결정 사항(2026-05-12):
- 정형 데이터는 LLM 추출 금지 → pdfplumber 결정론 경로.
- 한 PDF = 여러 연도(연도별 1페이지). 페이지별 컬럼 수가 12~14로 다름.
- 머지 셀은 None으로 옴 → 분류 컬럼만 forward-fill (학점 셀은 fill 안 함, 환각 방지).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

SEMESTER_LABELS = ["1-Ⅰ", "1-Ⅱ", "2-Ⅰ", "2-Ⅱ", "3-Ⅰ", "3-Ⅱ", "4-Ⅰ", "4-Ⅱ"]


def _clean(s):
    if s is None:
        return None
    s = s.replace("\n", " ").strip()
    s = re.sub(r" +", " ", s)
    return s or None


def _parse_year_label(page_text: str) -> str | None:
    for line in page_text.splitlines():
        line = line.strip()
        if "학년도" in line and ("입학" in line or "적용" in line):
            return line.lstrip("▣").strip()
    return None


def _find_columns(table: list[list]) -> dict:
    """헤더 두 행 기반 컬럼 식별."""
    header = table[0]
    subheader = table[1]

    course_name_col = next(
        i for i, c in enumerate(header)
        if c and "강" in c and "좌" in c and "명" in c
    )
    total_col = max(i for i, c in enumerate(header) if c and "계" in c)
    semester_cols = [i for i, c in enumerate(subheader) if c in ("Ⅰ", "Ⅱ")]
    if len(semester_cols) != 8:
        raise ValueError(f"semester cols expected 8, got {semester_cols}")

    classification_cols = list(range(course_name_col))
    note_cols = [
        i for i in range(course_name_col + 1, semester_cols[0])
        if i != course_name_col
    ]
    return {
        "course_name_col": course_name_col,
        "total_col": total_col,
        "semester_cols": semester_cols,
        "classification_cols": classification_cols,
        "note_cols": note_cols,
    }


def _parse_page(table: list[list], page_text: str, page_number: int) -> dict:
    cols = _find_columns(table)
    classification_cols = cols["classification_cols"]
    course_name_col = cols["course_name_col"]
    note_cols = cols["note_cols"]
    semester_cols = cols["semester_cols"]
    total_col = cols["total_col"]

    last_class: list[str | None] = [None] * len(classification_cols)
    courses: list[dict] = []
    subtotals: list[dict] = []

    for r in table[2:]:
        course_name = _clean(r[course_name_col])
        raw_class = [_clean(r[ci]) for ci in classification_cols]
        credits = {
            label: _clean(r[ci])
            for label, ci in zip(SEMESTER_LABELS, semester_cols)
        }
        total = _clean(r[total_col])
        has_credit_or_total = any(v for v in credits.values()) or bool(total)

        if not course_name and has_credit_or_total:
            # 합계/총계 등 집계 행: forward-fill 오염 방지 위해 last_class 갱신 안 함.
            label = next((v for v in raw_class if v), "(미상)")
            subtotals.append({
                "label": label,
                "credits": credits,
                "total": total,
            })
            continue

        # 일반 행: 분류 cell만 forward-fill. 상위 레벨이 갱신되면 하위 레벨 초기화
        # (전공필수가 균형교양 12학점 안에 들어가는 식의 오상속 방지).
        for i, v in enumerate(raw_class):
            if v:
                last_class[i] = v
                for j in range(i + 1, len(classification_cols)):
                    last_class[j] = None

        if course_name:
            note = " ".join(filter(None, (_clean(r[ci]) for ci in note_cols))) or None
            courses.append({
                "classification": [c for c in last_class if c],
                "name": course_name,
                "note": note,
                "credits": credits,
                "total": total,
            })

    return {
        "page_number": page_number,
        "year_label": _parse_year_label(page_text),
        "courses": courses,
        "subtotals": subtotals,
    }


def parse(pdf_path: str | Path) -> dict:
    """PDF의 모든 페이지를 연도별로 파싱."""
    import pdfplumber

    years: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            if not tables:
                continue
            txt = page.extract_text() or ""
            years.append(_parse_page(tables[0], txt, i))
    return {"years": years}


def render_text(parsed_year: dict) -> str:
    """한 연도 데이터를 사람이 읽기 좋은 텍스트로 직렬화. RAG 임베딩용."""
    lines: list[str] = []
    lines.append(f"[{parsed_year.get('year_label') or '교육과정'}]")
    lines.append("")

    by_class: "OrderedDict[str, list[dict]]" = OrderedDict()
    for c in parsed_year["courses"]:
        key = " > ".join(c["classification"]) if c["classification"] else "(미분류)"
        by_class.setdefault(key, []).append(c)

    for key, courses in by_class.items():
        lines.append(f"▣ {key}")
        for c in courses:
            sems = [f"{lbl} {v}학점" for lbl, v in c["credits"].items() if v]
            sems_text = ", ".join(sems) if sems else "학점 정보 없음"
            total_text = f" (총 {c['total']}학점)" if c["total"] else ""
            line = f"  - {c['name']}: {sems_text}{total_text}"
            if c["note"]:
                line += f" [{c['note']}]"
            lines.append(line)
        lines.append("")

    if parsed_year["subtotals"]:
        lines.append("[합계]")
        for st in parsed_year["subtotals"]:
            sems = [f"{lbl} {v}" for lbl, v in st["credits"].items() if v]
            sems_text = " / ".join(sems) if sems else ""
            total = st["total"] or "?"
            lines.append(f"  - {st['label']}: {sems_text} (총 {total}학점)")

    return "\n".join(lines)
