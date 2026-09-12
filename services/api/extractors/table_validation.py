"""Deterministic validation for OCR-derived tables.

Extraction models produce evidence (cell geometry, text, confidence).  This
module never invents text: it checks that evidence and identifies the small set
of cells that may need a vision-model or human review.
"""
from __future__ import annotations

import re
from typing import Any


LOW_CELL_CONFIDENCE = 0.75
MAX_UNASSIGNED_OCR_RATIO = 0.15

# Domain rules are declarative and only activate when every referenced label is
# present exactly once.  Adding a new document family does not change the table
# extractor itself.
TOTAL_RULES = (
    {
        "name": "curriculum_major_total",
        "result": r"^전공합계",
        "operands": (r"^전공필수합계", r"^전공선택합계"),
    },
    {
        "name": "curriculum_grand_total",
        "result": r"^총계",
        "operands": (r"^교양총소계", r"^전공합계"),
    },
)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _last_number(value: str) -> float | None:
    numbers = re.findall(r"(?<![\d(])\d+(?:\.\d+)?(?![\d)])", value or "")
    return float(numbers[-1]) if numbers else None


def _labeled_total(rows: list[dict[str, Any]], pattern: str) -> dict[str, Any] | None:
    matches = []
    compiled = re.compile(pattern)
    for row in rows:
        text = str(row.get("text") or "")
        if compiled.search(_normalized(text)):
            value = _last_number(text)
            if value is not None:
                matches.append({
                    "value": value,
                    "row": row,
                    # A numeric range in a total row normally means adjacent
                    # rows/columns were merged by structure recognition.  Do
                    # not turn that uncertain evidence into a false mismatch.
                    "ambiguous": bool(re.search(r"\d\s*[~～-]\s*\d", text)),
                })
    return matches[0] if len(matches) == 1 else None


def validate_extracted_tables(
    tables: list[dict[str, Any]],
    *,
    total_ocr_items: int = 0,
    assigned_ocr_items: int = 0,
    duplicate_rows_removed: int = 0,
) -> dict[str, Any]:
    """Return audit-friendly checks and review cells without changing content."""
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    review_cells: list[dict[str, Any]] = []

    if not tables:
        issues.append({"code": "no_table_detected", "severity": "warning"})

    for table_index, table in enumerate(tables, start=1):
        structure_confidence = float(table.get("structureConfidence") or 0.0)
        # OpenCV reports measured rule coverage, not a model probability. Pale
        # but consistently detected scanned rules therefore use a lower scale.
        minimum_structure_confidence = (
            0.40 if table.get("structureEngine") == "opencv-grid" else 0.70
        )
        if structure_confidence < minimum_structure_confidence:
            issues.append({
                "code": "low_structure_confidence",
                "severity": "warning",
                "table": table_index,
                "value": round(structure_confidence, 4),
            })
        for row_index, row in enumerate(table.get("rows") or [], start=1):
            for cell_index, cell in enumerate(row.get("cells") or [], start=1):
                text = str(cell.get("text") or "").strip()
                confidence = cell.get("confidence")
                if text and confidence is not None and float(confidence) < LOW_CELL_CONFIDENCE:
                    review_cells.append({
                        "table": table_index,
                        "pageNumber": table.get("pageNumber"),
                        "row": row_index,
                        "cell": cell_index,
                        "text": text,
                        "rowText": row.get("text"),
                        "confidence": round(float(confidence), 4),
                        "bbox": cell.get("bbox"),
                        "reason": "low_ocr_confidence",
                    })

    unassigned = max(0, total_ocr_items - assigned_ocr_items)
    unassigned_ratio = unassigned / total_ocr_items if total_ocr_items else 0.0
    if total_ocr_items and unassigned_ratio > MAX_UNASSIGNED_OCR_RATIO:
        issues.append({
            "code": "high_unassigned_ocr_ratio",
            "severity": "warning",
            "value": round(unassigned_ratio, 4),
        })

    rows = [row for table in tables for row in table.get("rows") or []]
    for rule in TOTAL_RULES:
        result = _labeled_total(rows, rule["result"])
        operands = [_labeled_total(rows, pattern) for pattern in rule["operands"]]
        if result is None or any(value is None for value in operands):
            continue
        evidence = [result, *(value for value in operands if value is not None)]
        if any(value["ambiguous"] for value in evidence):
            check = {
                "name": rule["name"],
                "status": "indeterminate",
                "reason": "merged_or_ranged_total_evidence",
            }
            checks.append(check)
            issues.append({
                "code": "ambiguous_total_evidence",
                "severity": "warning",
                **check,
            })
            continue
        expected = sum(value["value"] for value in operands if value is not None)
        actual = result["value"]
        passed = abs(actual - expected) < 1e-6
        check = {
            "name": rule["name"],
            "status": "passed" if passed else "failed",
            "actual": actual,
            "expected": expected,
        }
        checks.append(check)
        if not passed:
            issues.append({
                "code": "total_mismatch",
                "severity": "error",
                **check,
            })

    return {
        "status": "review" if issues or review_cells else "passed",
        "requiresReview": bool(issues or review_cells),
        "issues": issues,
        "checks": checks,
        "reviewCells": review_cells,
        "metrics": {
            "tableCount": len(tables),
            "rowCount": len(rows),
            "totalOcrItems": total_ocr_items,
            "assignedOcrItems": assigned_ocr_items,
            "unassignedOcrItems": unassigned,
            "unassignedOcrRatio": round(unassigned_ratio, 4),
            "duplicateRowsRemoved": duplicate_rows_removed,
        },
    }
