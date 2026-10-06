from pathlib import Path

from crawlers.methods import curriculum_page
from crawlers.methods.curriculum_page import (
    CurriculumConfig,
    CurriculumCrawler,
    CurriculumDocumentConfig,
)


def test_multiple_curriculum_documents_are_kept_in_one_source(monkeypatch, tmp_path):
    documents = (
        CurriculumDocumentConfig("2026", "https://example.test/2026.pdf", tmp_path / "2026.pdf"),
        CurriculumDocumentConfig("2025", "https://example.test/2025.pdf", tmp_path / "2025.pdf"),
    )
    for document in documents:
        document.cache_path.write_bytes(f"{document.label}-pdf".encode())
    crawler = CurriculumCrawler(CurriculumConfig(
        source_code="test_curriculum",
        source_name="테스트 교육과정표",
        department="테스트학과",
        base_url="https://example.test",
        pdf_url=documents[0].pdf_url,
        page_url="https://example.test/curriculum",
        cache_path=Path("unused.pdf"),
        documents=documents,
    ))
    monkeypatch.setattr(crawler, "_download_document", lambda document: document.cache_path)
    monkeypatch.setattr(
        curriculum_page,
        "parse",
        lambda path: {
            "years": [{
                "year_label": path.stem,
                "page_number": 1,
                "applicable_years": [int(path.stem)],
                "lead_sentence": "적용 연도",
                "markdown_table": "| 과목 | 학점 |",
            }],
        },
    )

    results = crawler.crawling()

    assert len(results) == 2
    assert [item["replace_by_source"] for item in results] == [True, False]
    assert [item["extra"]["document_label"] for item in results] == ["2026", "2025"]
    assert results[0]["url"].startswith("https://example.test/2026.pdf?")
    assert results[1]["url"].startswith("https://example.test/2025.pdf?")


def test_document_options_are_discovered_from_curriculum_page(monkeypatch, tmp_path):
    crawler = CurriculumCrawler(CurriculumConfig(
        source_code="dynamic_curriculum",
        source_name="동적 교육과정표",
        department="테스트학과",
        base_url="https://example.test",
        pdf_url="https://example.test/fallback.pdf",
        page_url="https://example.test/curriculum",
        cache_path=tmp_path / "fallback.pdf",
        document_selector="#viewerDocSelector option",
        document_url_template="https://example.test/{document_id}/fileDown.do",
        document_cache_dir=tmp_path,
    ))
    monkeypatch.setattr(
        crawler,
        "_fetch_document_list_html",
        lambda: """
            <select id="viewerDocSelector">
              <option value="1261">2011~2026 교육과정표</option>
              <option value="1300">2027 교육과정표</option>
            </select>
        """,
    )

    documents = crawler._documents()

    assert [document.label for document in documents] == [
        "2011~2026 교육과정표",
        "2027 교육과정표",
    ]
    assert [document.pdf_url for document in documents] == [
        "https://example.test/1261/fileDown.do",
        "https://example.test/1300/fileDown.do",
    ]
    assert [document.cache_path for document in documents] == [
        tmp_path / "1261.pdf",
        tmp_path / "1300.pdf",
    ]


def test_unchanged_curriculum_pdf_reuses_parse_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "curriculum.pdf"
    cache_path.write_bytes(b"same-pdf")
    crawler = CurriculumCrawler(CurriculumConfig(
        source_code="test_curriculum",
        source_name="테스트 교육과정표",
        department="테스트학과",
        base_url="https://example.test",
        pdf_url="https://example.test/curriculum.pdf",
        page_url="https://example.test/curriculum",
        cache_path=cache_path,
    ))
    monkeypatch.setattr(crawler, "_download_document", lambda document: cache_path)
    parsed = {
        "years": [{
            "year_label": "2026",
            "page_number": 1,
            "applicable_years": [2026],
            "lead_sentence": "적용 연도",
            "markdown_table": "| 과목 | 학점 |",
        }],
    }
    document_hash = crawler._file_sha256(cache_path)
    assert document_hash is not None
    crawler._store_parse_cache(cache_path, document_hash, parsed)

    def fail_if_parsed(_path):
        raise AssertionError("unchanged PDF must reuse its parse cache")

    monkeypatch.setattr(curriculum_page, "parse", fail_if_parsed)

    results = crawler.crawling()

    assert len(results) == 1
    assert results[0]["replace_by_source"] is True


def test_changed_curriculum_pdf_runs_parser(monkeypatch, tmp_path):
    cache_path = tmp_path / "curriculum.pdf"
    cache_path.write_bytes(b"old-pdf")
    crawler = CurriculumCrawler(CurriculumConfig(
        source_code="test_curriculum",
        source_name="테스트 교육과정표",
        department="테스트학과",
        base_url="https://example.test",
        pdf_url="https://example.test/curriculum.pdf",
        page_url="https://example.test/curriculum",
        cache_path=cache_path,
    ))

    def download_changed(_document):
        cache_path.write_bytes(b"new-pdf")
        return cache_path

    parsed_paths = []

    def parse_changed(path):
        parsed_paths.append(path)
        return {
            "years": [{
                "year_label": "2026",
                "page_number": 1,
                "applicable_years": [2026],
                "lead_sentence": "적용 연도",
                "markdown_table": "| 과목 | 학점 |",
            }],
        }

    monkeypatch.setattr(crawler, "_download_document", download_changed)
    monkeypatch.setattr(curriculum_page, "parse", parse_changed)

    results = crawler.crawling()

    assert parsed_paths == [cache_path]
    assert len(results) == 1
    assert results[0]["replace_by_source"] is True


def test_only_changed_pdf_is_parsed_in_multi_document_source(monkeypatch, tmp_path):
    unchanged_path = tmp_path / "unchanged.pdf"
    changed_path = tmp_path / "changed.pdf"
    unchanged_path.write_bytes(b"unchanged-pdf")
    changed_path.write_bytes(b"old-pdf")
    documents = (
        CurriculumDocumentConfig(
            "2025", "https://example.test/2025.pdf", unchanged_path
        ),
        CurriculumDocumentConfig(
            "2026", "https://example.test/2026.pdf", changed_path
        ),
    )
    crawler = CurriculumCrawler(CurriculumConfig(
        source_code="software_curriculum",
        source_name="소프트웨어학과 교과과정표",
        department="소프트웨어학과",
        base_url="https://example.test",
        pdf_url=documents[0].pdf_url,
        page_url="https://example.test/curriculum",
        cache_path=Path("unused.pdf"),
        documents=documents,
    ))

    cached_parse = {
        "years": [{
            "year_label": "2025",
            "page_number": 1,
            "applicable_years": [2025],
            "lead_sentence": "적용 연도",
            "markdown_table": "| 2025 과목 | 학점 |",
        }],
    }
    unchanged_hash = crawler._file_sha256(unchanged_path)
    assert unchanged_hash is not None
    crawler._store_parse_cache(unchanged_path, unchanged_hash, cached_parse)

    def download(document):
        if document.cache_path == changed_path:
            changed_path.write_bytes(b"new-pdf")
        return document.cache_path

    parsed_paths = []

    def parse_changed(path):
        parsed_paths.append(path)
        return {
            "years": [{
                "year_label": "2026",
                "page_number": 1,
                "applicable_years": [2026],
                "lead_sentence": "적용 연도",
                "markdown_table": "| 2026 과목 | 학점 |",
            }],
        }

    monkeypatch.setattr(crawler, "_download_document", download)
    monkeypatch.setattr(curriculum_page, "parse", parse_changed)

    results = crawler.crawling()

    assert parsed_paths == [changed_path]
    assert len(results) == 2
    assert [item["replace_by_source"] for item in results] == [True, False]
