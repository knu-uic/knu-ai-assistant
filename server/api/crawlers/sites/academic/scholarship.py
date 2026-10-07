from crawlers.methods.static_page import StaticPageConfig, StaticPageCrawler


SCHOLARSHIP_CRAWLERS = {
    "scholarship_info": StaticPageCrawler(StaticPageConfig(
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
    )),
}
