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
