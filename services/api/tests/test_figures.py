from api.figures import collect_related_figures, related_figures


def test_related_figures_matches_document_reference_number():
    figures = [
        {"asset_id": 10, "number": 1, "label": "그림 1", "url": "/one"},
        {"asset_id": 11, "number": 2, "label": "그림 2", "url": "/two"},
    ]

    assert related_figures(figures, "[그림 2] 균형교양 필터") == [{
        "asset_id": 11,
        "reference": "[그림:11]",
        "number": 2,
        "label": "그림 2",
        "filename": None,
        "description": None,
        "context": None,
        "url": "/two",
    }]


def test_collect_related_figures_deduplicates_asset():
    image = {"asset_id": 10, "number": 1}
    assert collect_related_figures([image], [image]) == [image]


def test_related_figures_matches_body_marker_without_colliding_with_attachment_number():
    figures = [
        {"asset_id": 20, "number": 1, "label": "본문 그림 1", "marker": "[본문 그림 1]", "url": "/body"},
        {"asset_id": 21, "number": 1, "label": "그림 1", "marker": "[그림 1]", "url": "/attachment"},
    ]

    result = related_figures(figures, "메뉴 설명\n[본문 그림 1]\n저장 버튼")

    assert [image["asset_id"] for image in result] == [20]
    assert result[0]["reference"] == "[그림:20]"
