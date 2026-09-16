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


def test_review_required_item_keeps_notice_and_original_assets_but_marks_review(monkeypatch):
    import pipelines.ingest as ingest

    item = {
        "url": "https://example.test/review",
        "title": "검토 필요 HWP",
        "review_required": True,
        "review_reason": "hwp_cross_validation_below_threshold",
        "extraction_quality": [{"score": 0.7}],
        "body_content": "공지 본문",
        "assets": [{"kind": "attachment_hwp", "source_url": "https://example.test/a.hwp"}],
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
    monkeypatch.setattr(ingest, "document_is_current", lambda url: False)
    monkeypatch.setattr(
        ingest,
        "upsert_extraction_review",
        lambda source_id, value: reviewed.append((source_id, value)),
    )
    class Doc:
        title = "검토 필요 HWP"
        content = "공지 본문"
        url = item["url"]
        category = "일반(기타)"
        target = None
        start_date = None
        end_date = None
        keywords = []
        summary = "요약"
        topics = []
        series_key = None
        periods = []
        audiences = []
        application = None
        extraction_confidence = 0.5

    inserted_assets = []
    monkeypatch.setattr(ingest, "refine", lambda values: [(Doc(), item["assets"], None)])
    monkeypatch.setattr(ingest, "insert_document", lambda **kwargs: 77)
    monkeypatch.setattr(ingest, "insert_assets", lambda notice_id, assets: inserted_assets.extend(assets))
    monkeypatch.setattr(ingest, "insert_chunks", lambda *args: None)
    monkeypatch.setattr(ingest, "embed_document_chunks", lambda **kwargs: [])
    monkeypatch.setattr(ingest, "clear_extraction_review", lambda url: (_ for _ in ()).throw(AssertionError("review must remain")))

    result = ingest.run_ingest()

    assert reviewed == [(9, item)]
    assert result["review"] == 1
    assert result["inserted"] == 1
    assert inserted_assets == item["assets"]


def test_paged_notice_is_raw_saved_before_llm_refinement(monkeypatch):
    import embedding.rebuild as rebuild
    import pipelines.ingest as ingest

    item = {
        "url": "https://example.test/immediate",
        "title": "즉시 저장 공지",
        "content": "본문",
        "body_content": "본문",
        "date": "2026-09-16",
        "assets": [{"kind": "attachment", "source_url": "https://example.test/a.pdf"}],
        "_crawl_page": 1,
    }

    class PagedCrawler:
        SOURCE_CODE = "paged"
        SOURCE_NAME = "페이지 공지"
        KIND = "notice"
        DEPARTMENT = "공통"
        BASE_URL = "https://example.test"

        def detect_total_pages(self):
            return 1

        def collect_pinned_urls(self):
            return set()

        def crawling(self, **kwargs):
            kwargs["on_detail_ready"](item)
            assert item["_raw_saved"] is True
            yield item

    class Doc:
        title = item["title"]
        content = item["content"]
        url = item["url"]
        category = "일반(기타)"
        target = None
        start_date = None
        end_date = None
        keywords = []
        summary = "요약"
        topics = []
        series_key = None
        periods = []
        audiences = []
        application = None
        extraction_confidence = 0.9

    inserts = []
    asset_writes = []
    progress = []
    monkeypatch.setattr(ingest, "CRAWLERS", [PagedCrawler()])
    monkeypatch.setattr(ingest, "init_db", lambda: None)
    monkeypatch.setattr(ingest, "sync_pinned_urls", lambda _urls: None)
    monkeypatch.setattr(ingest, "archive_documents", lambda **_kwargs: 0)
    monkeypatch.setattr(ingest, "upsert_source", lambda **_kwargs: 5)
    monkeypatch.setattr(ingest, "select_crawl_records", lambda _sid, records, **_kwargs: records)
    monkeypatch.setattr(ingest, "insert_document", lambda **kwargs: inserts.append(kwargs) or 41)
    monkeypatch.setattr(ingest, "insert_assets", lambda notice_id, assets: asset_writes.append((notice_id, assets)))
    monkeypatch.setattr(ingest, "refine", lambda _values: [(Doc(), item["assets"], None)])
    monkeypatch.setattr(ingest, "embed_document_chunks", lambda **_kwargs: [])
    monkeypatch.setattr(ingest, "insert_chunks", lambda *_args: None)
    monkeypatch.setattr(ingest, "mark_crawl_url_completed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ingest, "clear_extraction_review", lambda _url: None)
    monkeypatch.setattr(rebuild, "sync_stale_datasets", lambda: None)

    result = ingest.run_ingest(on_progress=progress.append)

    assert [call.get("extraction_version") for call in inserts] == ["raw-v1", None]
    assert asset_writes == [(41, item["assets"])]
    assert [event["status"] for event in progress if event.get("url") == item["url"]] == [
        "stored", "refining", "complete",
    ]
    assert sum(event.get("saved_increment", 0) for event in progress) == 1
    assert result["inserted"] == 1
