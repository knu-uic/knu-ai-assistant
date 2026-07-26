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


def test_retrieve_mcp_evidence_uses_precise_retrieval_without_answerer(monkeypatch):
    monkeypatch.setattr(
        graph,
        "router_node",
        lambda state: {
            "query_mode": "precise",
            "categories": ["수강"],
            "expanded_query": "확장된 수강 철회",
            "route_rationale": "구체 질문",
        },
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_with_rerank",
        lambda query, major, categories: ([{"title": "공지"}], [{"chunk": "근거"}]),
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_broad",
        lambda *args: (_ for _ in ()).throw(AssertionError("broad retrieval called")),
    )

    result = graph.retrieve_mcp_evidence("수강 철회", major="컴퓨터학부")

    assert result == {
        "query_mode": "precise",
        "original_query": "수강 철회",
        "expanded_query": "확장된 수강 철회",
        "categories": ["수강"],
        "routing_fallback": False,
        "contexts": [{"title": "공지"}],
        "evidence_chunks": [{"chunk": "근거"}],
    }


def test_retrieve_mcp_evidence_uses_broad_retrieval_and_category_override(monkeypatch):
    monkeypatch.setattr(
        graph,
        "router_node",
        lambda state: {
            "query_mode": "broad",
            "categories": ["일반(기타)"],
            "expanded_query": "주요 수강 공지",
            "route_rationale": "목록 질문",
        },
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_broad",
        lambda query, major, categories: [{"title": f"{query}:{major}:{categories[0]}"}],
    )

    result = graph.retrieve_mcp_evidence(
        "수강 공지 목록",
        major="컴퓨터학부",
        category_override="수강",
    )

    assert result["query_mode"] == "broad"
    assert result["categories"] == ["수강"]
    assert result["contexts"] == [{"title": "주요 수강 공지:컴퓨터학부:수강"}]
    assert result["evidence_chunks"] == []


def test_retrieve_mcp_evidence_returns_smalltalk_without_search(monkeypatch):
    monkeypatch.setattr(
        graph,
        "router_node",
        lambda state: {
            "query_mode": "smalltalk",
            "categories": [],
            "expanded_query": "안녕",
            "route_rationale": "검색 불필요",
        },
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_with_rerank",
        lambda *args: (_ for _ in ()).throw(AssertionError("precise retrieval called")),
    )
    monkeypatch.setattr(
        graph,
        "_retrieve_broad",
        lambda *args: (_ for _ in ()).throw(AssertionError("broad retrieval called")),
    )

    result = graph.retrieve_mcp_evidence("안녕")

    assert result["query_mode"] == "smalltalk"
    assert result["contexts"] == []
    assert result["evidence_chunks"] == []


def test_retrieve_mcp_evidence_falls_back_to_original_precise_query(monkeypatch):
    def fail_router(state):
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(graph, "router_node", fail_router)
    monkeypatch.setattr(
        graph,
        "_retrieve_with_rerank",
        lambda query, major, categories: (
            [{"title": f"{query}:{major}:{categories}"}],
            [],
        ),
    )

    result = graph.retrieve_mcp_evidence("원본 질문", major="컴퓨터학부")

    assert result["query_mode"] == "precise"
    assert result["expanded_query"] == "원본 질문"
    assert result["categories"] == []
    assert result["routing_fallback"] is True
    assert result["contexts"] == [{"title": "원본 질문:컴퓨터학부:None"}]


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
    monkeypatch.setattr(graph, "_vector_search", lambda *args: [row])
    monkeypatch.setattr(graph, "_rerank", lambda query, rows: [(row, 0.94)])
    monkeypatch.setattr(graph, "get_document_content", lambda category, url: "공지 본문")

    contexts, evidence = graph._retrieve_with_rerank("수강 철회", None, ["수강"])

    assert contexts[0]["category"] == "수강"
    assert contexts[0]["vector_score"] == 0.81
    assert contexts[0]["rerank_score"] == 0.94
    assert evidence[0]["vector_score"] == 0.81
    assert evidence[0]["rerank_score"] == 0.94
