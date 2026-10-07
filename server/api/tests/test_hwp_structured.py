from extractors.hwp_structured import (
    _figure_appendix,
    _figure_search_contents,
    _insert_figure_descriptions,
    _number_figure_placements,
)


def test_hwp_figures_keep_picture_record_id_and_surrounding_context():
    blocks = [
        {"type": "paragraph", "text": "학문기초교양 과목을 필터링한다."},
        {
            "type": "table",
            "rows": 1,
            "columns": 1,
            "cells": [{"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1, "text": "[그림]"}],
        },
        {"type": "paragraph", "text": "본인이 선택하여 3학점 이수한다."},
        {
            "type": "table",
            "rows": 1,
            "columns": 2,
            "cells": [
                {"row": 0, "column": 0, "rowSpan": 1, "columnSpan": 1, "text": "일반교양"},
                {"row": 0, "column": 1, "rowSpan": 1, "columnSpan": 1, "text": "필터링 [그림]"},
            ],
        },
    ]

    figures = _number_figure_placements(blocks, [4, 2])

    assert blocks[1]["cells"][0]["text"] == "[그림 1]"
    assert blocks[3]["cells"][1]["text"] == "필터링 [그림 2]"
    assert figures[0]["binaryId"] == 4
    assert "학문기초교양" in figures[0]["context"]
    assert "3학점" in figures[0]["context"]
    assert figures[1]["binaryId"] == 2
    assert "일반교양 | 필터링 [그림]" in figures[1]["context"]
    assert figures[1]["matchMethod"] == "hwp_picture_record_bin_item_id"


def test_figure_appendix_only_uses_reviewed_search_text():
    figures = [
        {"number": 1, "context": "학문기초교양 필터", "analysis": {"searchText": "엑셀 필터 화면"}},
        {"number": 2, "context": "다른 문맥", "analysis": {"searchText": "불확실", "requiresReview": True}},
    ]

    appendix = _figure_appendix(figures)

    assert "[그림 1]" in appendix
    assert "엑셀 필터 화면" in appendix
    assert "[그림 2]" not in appendix
    contents = _figure_search_contents(figures)
    assert len(contents) == 1
    assert contents[0]["text"].startswith("[그림 1]\n")


def test_figure_description_is_inserted_at_original_marker_not_document_end():
    figures = [{
        "number": 1,
        "analysis": {
            "description": "학문기초교양만 선택하는 엑셀 필터 예시다.",
            "ocrText": "2017~2020학년도 학문기초교양",
        },
    }]
    source = "위 문장\n\n| [그림 1] |\n| --- |\n\n아래 문장"

    rendered = _insert_figure_descriptions(source, figures, markdown=True)

    assert "[그림 1]<br>[그림 설명]" in rendered
    assert "[그림 내 텍스트] 2017~2020" in rendered
    assert rendered.index("학문기초교양만") < rendered.index("아래 문장")


def test_unreviewed_figure_description_is_not_inserted():
    source = "본문 [그림 1] 뒤 문장"
    figures = [{
        "number": 1,
        "analysis": {"description": "불확실한 설명", "requiresReview": True},
    }]

    assert _insert_figure_descriptions(source, figures, markdown=False) == source
