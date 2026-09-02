def test_time_based_archive_still_runs_when_crawl_returns_no_items(monkeypatch):
    import pipelines.ingest as ingest

    class FailedCrawler:
        SOURCE_CODE = "failed"
        SOURCE_NAME = "실패 게시판"
        KIND = "notice"
        DEPARTMENT = "공통"
        BASE_URL = "https://example.test"
        last_run_stats = {
            "discovered": 16,
            "known": 0,
            "succeeded": 0,
            "failed": 16,
            "accepted_pages": 0,
            "rejected_pages": 1,
        }

        def collect_pinned_urls(self):
            return set()

        def crawling(self, should_skip=None):
            return iter(())

    archived = []
    monkeypatch.setattr(ingest, "CRAWLERS", [FailedCrawler()])
    monkeypatch.setattr(ingest, "init_db", lambda: None)
    monkeypatch.setattr(ingest, "sync_pinned_urls", lambda urls: None)
    monkeypatch.setattr(
        ingest,
        "archive_documents",
        lambda retention_months, protected_urls: archived.append(
            (retention_months, protected_urls)
        ),
    )
    monkeypatch.setattr(ingest, "upsert_source", lambda **kwargs: 1)

    result = ingest.run_ingest()

    assert archived == [(24, set())]
    assert result == {
        "crawled": 0,
        "inserted": 0,
        "skipped": 0,
        "dropped": 0,
        "review": 0,
    }


def test_review_required_item_is_quarantined_before_refine(monkeypatch):
    import pipelines.ingest as ingest

    item = {
        "url": "https://example.test/review",
        "title": "검토 필요 HWP",
        "review_required": True,
        "review_reason": "hwp_cross_validation_below_threshold",
        "extraction_quality": [{"score": 0.7}],
        "assets": [],
    }

    class ReviewCrawler:
        SOURCE_CODE = "review"
        SOURCE_NAME = "검토 게시판"
        KIND = "notice"
        DEPARTMENT = "공통"
        BASE_URL = "https://example.test"

        def collect_pinned_urls(self):
            return set()

        def crawling(self, should_skip=None):
            yield item

    reviewed = []
    monkeypatch.setattr(ingest, "CRAWLERS", [ReviewCrawler()])
    monkeypatch.setattr(ingest, "init_db", lambda: None)
    monkeypatch.setattr(ingest, "sync_pinned_urls", lambda urls: None)
    monkeypatch.setattr(ingest, "archive_documents", lambda **kwargs: 0)
    monkeypatch.setattr(ingest, "upsert_source", lambda **kwargs: 9)
    monkeypatch.setattr(ingest, "document_exists", lambda url: False)
    monkeypatch.setattr(
        ingest,
        "upsert_extraction_review",
        lambda source_id, value: reviewed.append((source_id, value)),
    )
    monkeypatch.setattr(
        ingest,
        "refine",
        lambda values: (_ for _ in ()).throw(AssertionError("must not refine")),
    )

    result = ingest.run_ingest()

    assert reviewed == [(9, item)]
    assert result["review"] == 1
    assert result["inserted"] == 0
