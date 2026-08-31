"""router query_mode → 경로 매핑 단위 테스트."""
from retrieval import graph
from retrieval.graph import _route_by_mode


def test_smalltalk_routes_to_smalltalk():
    assert _route_by_mode({"query_mode": "smalltalk"}) == "smalltalk"


def test_broad_routes_to_broad():
    assert _route_by_mode({"query_mode": "broad"}) == "broad"


def test_precise_routes_to_precise():
    assert _route_by_mode({"query_mode": "precise"}) == "precise"


def test_unknown_defaults_to_precise():
    assert _route_by_mode({}) == "precise"


def test_retrieve_mcp_evidence_uses_deep_retrieval_without_answerer(monkeypatch):
    monkeypatch.setattr(
        graph,
        "_retrieve_with_rerank",
        lambda query, major, categories, **kwargs: (
            [{"title": f"공지:{kwargs['time_scope']}:{kwargs['year']}"}],
            [{"chunk": "근거"}],
        ),
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_broad",
        lambda *args: (_ for _ in ()).throw(AssertionError("broad retrieval called")),
    )

    result = graph.retrieve_mcp_evidence(
        "수강 철회",
        department="컴퓨터학부",
        category_override="수강",
        time_scope="current",
        year=2026,
        notice_ids=[9],
    )

    assert result == {
        "query_mode": "deep",
        "original_query": "수강 철회",
        "expanded_query": "수강 철회",
        "categories": ["수강"],
        "department": "컴퓨터학부",
        "time_scope": "current",
        "year": 2026,
        "notice_ids": [9],
        "routing_fallback": False,
        "contexts": [{"title": "공지:current:2026"}],
        "evidence_chunks": [{"chunk": "근거"}],
    }


def test_retrieve_mcp_evidence_does_not_call_llm_router(monkeypatch):
    monkeypatch.setattr(
        graph,
        "router_node",
        lambda state: (_ for _ in ()).throw(AssertionError("LLM router called")),
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_with_rerank",
        lambda query, major, categories, **_kwargs: (
            [{"title": f"{query}:{major}:{categories}"}],
            [],
        ),
    )

    result = graph.retrieve_mcp_evidence("원본 질문", department="컴퓨터학부")

    assert result["query_mode"] == "deep"
    assert result["expanded_query"] == "원본 질문"
    assert result["categories"] == []
    assert result["routing_fallback"] is False
    assert result["contexts"] == [{"title": "원본 질문:컴퓨터학부:None"}]


def test_rerank_falls_back_to_vector_scores(monkeypatch):
    rows = [
        ("url-a", "A", "a", 0.2),
        ("url-b", "B", "b", 0.8),
    ]
    monkeypatch.setattr(
        graph,
        "rerank_scores",
        lambda *args: (_ for _ in ()).throw(RuntimeError("reranker unavailable")),
    )

    ranked = graph._rerank("query", rows)

    assert [row[0] for row, _ in ranked] == ["url-b", "url-a"]
    assert [score for _, score in ranked] == [0.8, 0.2]


def test_precise_retrieval_preserves_vector_and_rerank_scores(monkeypatch):
    row = (
        "https://x/notice",
        "수강 철회 공지",
        "검색 청크",
        0.81,
        None,
        None,
        None,
        "수강",
        [],
        [],
        "KNU",
        "학사과",
        "notice",
        None,
        "요약",
        "공지 본문",
        ["안내.pdf"],
    )
    monkeypatch.setattr(graph, "embed_query", lambda query: [0.1])
    monkeypatch.setattr(graph, "_vector_search", lambda *args, **kwargs: [row])
    monkeypatch.setattr(graph, "_rerank", lambda query, rows: [(row, 0.94)])
    monkeypatch.setattr(graph, "get_document_content", lambda url, category: "공지 본문")

    contexts, evidence = graph._retrieve_with_rerank("수강 철회", None, ["수강"])

    assert contexts[0]["category"] == "수강"
    assert contexts[0]["vector_score"] == 0.81
    assert contexts[0]["rerank_score"] == 0.94
    assert evidence[0]["vector_score"] == 0.81
    assert evidence[0]["rerank_score"] == 0.94
