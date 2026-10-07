from extractors.table_validation import validate_extracted_tables


def _table(*rows):
    return [{
        "structureConfidence": 0.96,
        "rows": [
            {
                "text": text,
                "cells": [{"text": text, "confidence": confidence, "bbox": [0, index, 10, index + 1]}],
            }
            for index, (text, confidence) in enumerate(rows)
        ],
    }]


def test_curriculum_totals_are_checked_by_deterministic_rules():
    result = validate_extracted_tables(_table(
        ("교양 총 소계 36", 0.99),
        ("전공필수 합계 72", 0.99),
        ("전공선택 합계 32", 0.99),
        ("전공합계 104", 0.99),
        ("총계 140", 0.99),
    ), total_ocr_items=5, assigned_ocr_items=5)

    assert result["status"] == "passed"
    assert [check["status"] for check in result["checks"]] == ["passed", "passed"]


def test_mismatch_and_low_confidence_are_reviewed_without_changing_text():
    result = validate_extracted_tables(_table(
        ("전공필수 합계 72", 0.99),
        ("전공선택 합계 32", 0.99),
        ("전공합계 103", 0.61),
    ), total_ocr_items=4, assigned_ocr_items=3)

    assert result["status"] == "review"
    assert result["checks"][0]["status"] == "failed"
    assert result["issues"][0]["code"] == "high_unassigned_ocr_ratio"
    assert result["reviewCells"][0]["text"] == "전공합계 103"


def test_merged_numeric_range_makes_total_check_indeterminate():
    result = validate_extracted_tables(_table(
        ("전공필수 합계 72", 0.99),
        ("전공선택 합계 32", 0.99),
        ("전공합계 104 일반선택 1~19", 0.99),
    ))

    assert result["checks"][0]["status"] == "indeterminate"
    assert result["issues"][0]["code"] == "ambiguous_total_evidence"


def test_opencv_rule_coverage_uses_geometry_specific_threshold():
    tables = _table(("총계 140", 0.99))
    tables[0]["structureEngine"] = "opencv-grid"
    tables[0]["structureConfidence"] = 0.49

    result = validate_extracted_tables(tables, total_ocr_items=1, assigned_ocr_items=1)

    assert not any(issue["code"] == "low_structure_confidence" for issue in result["issues"])
