from crawlers.methods.static_page import StaticPageConfig, StaticPageCrawler


class _Response:
    text = "<article><h2>장학안내</h2><p>1학기 신청은 12월 중입니다.</p></article>"

    def raise_for_status(self):
        return None


def test_static_page_returns_deterministic_refined_metadata(monkeypatch):
    crawler = StaticPageCrawler(StaticPageConfig(
        source_code="scholarship_info",
        source_name="공주대학교 장학안내",
        department="공통",
        kind="academic",
        base_url="https://www.kongju.ac.kr",
        page_url="https://www.kongju.ac.kr/KNU/16842/subview.do",
        wait_selector="article",
        title_selector="h2",
        content_selector="article",
        category="장학",
        keywords=("장학", "장학금", "지원"),
    ))
    monkeypatch.setattr(crawler.session, "get", lambda *args, **kwargs: _Response())

    result = crawler.crawling()

    assert len(result) == 1
    assert result[0]["pre_refined"] is True
    assert result[0]["metadata"]["title"] == "장학안내"
    assert result[0]["metadata"]["category"] == "장학"
    assert result[0]["metadata"]["keywords"] == ["장학", "장학금", "지원"]
    assert "12월" in result[0]["metadata"]["summary"]


def test_static_page_preserves_table_rows_and_spans(monkeypatch):
    class TableResponse:
        text = """
        <article><h2>장학안내</h2><h3>학부 교내장학금</h3>
        <table><caption>장학금 수혜 조건</caption><thead><tr>
          <th colspan="2">장학금종류</th><th>수혜요건</th><th>장학금액</th>
        </tr></thead><tbody>
          <tr><td rowspan="2">성적우수</td><td>수석</td><td>최상위자</td><td>전액</td></tr>
          <tr><td>우수</td><td>30%</td><td>20%</td></tr>
        </tbody></table></article>
        """

        def raise_for_status(self):
            return None

    crawler = StaticPageCrawler(StaticPageConfig(
        source_code="scholarship_info",
        source_name="공주대학교 장학안내",
        department="공통",
        kind="academic",
        base_url="https://www.kongju.ac.kr",
        page_url="https://www.kongju.ac.kr/KNU/16842/subview.do",
        wait_selector="article",
        title_selector="h2",
        content_selector="article",
        category="장학",
    ))
    monkeypatch.setattr(crawler.session, "get", lambda *args, **kwargs: TableResponse())

    item = crawler.crawling()[0]

    assert "| 장학금종류 (1) | 장학금종류 (2) | 수혜요건 | 장학금액 |" in item["body_content"]
    assert "| 성적우수 | 우수 | 30% | 20% |" in item["body_content"]
    table = item["extra"]["tables"][0]
    assert table["section"] == "학부 교내장학금"
    assert table["rows"][1]["장학금종류 (1)"] == "성적우수"
    assert table["source_cells"][0]["column_span"] == 2
    assert table["source_cells"][3]["row_span"] == 2
