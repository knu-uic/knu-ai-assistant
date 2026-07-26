import datetime
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _mcp_request(client, payload, token=None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/api/mcp", headers=headers, json=payload)


def _tool_call(client, token, name, arguments):
    result = _tool_call_result(client, token, name, arguments)
    return json.loads(result["content"][0]["text"])


def _tool_call_result(client, token, name, arguments):
    response = _mcp_request(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        token,
    )
    assert response.status_code == 200
    return response.json()["result"]


@pytest.mark.parametrize(
    ("token", "expected_status"),
    [
        (None, 401),
        ("wrong-mcp-token", 401),
        ("unit-mcp-token", 200),
    ],
)
def test_mcp_accepts_only_configured_bearer_token(monkeypatch, token, expected_status):
    import api.mcp_server as mcp_mod

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    with TestClient(app) as client:
        response = _mcp_request(client, payload, token)

    assert response.status_code == expected_status


def test_mcp_lists_only_notice_evidence_tools(monkeypatch):
    import api.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    with TestClient(app) as client:
        response = _mcp_request(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            "unit-mcp-token",
        )

    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "search_knu_notices",
        "get_knu_notice_detail",
    }
    search_tool = next(tool for tool in tools if tool["name"] == "search_knu_notices")
    assert "수강/학사/장학 공지" in search_tool["description"]


def test_search_knu_notices_clamps_result_limit_and_returns_safe_fields(monkeypatch):
    import api.mcp_server as mcp_mod

    def fake_retrieve(query, major, category_override):
        assert (query, major, category_override) == ("수강 철회", None, None)
        return {
            "query_mode": "precise",
            "original_query": query,
            "expanded_query": "2026학년도 수강 철회 신청 기간",
            "categories": ["수강"],
            "routing_fallback": False,
            "contexts": [
                {
                    "url": "https://x/9",
                    "title": "검색결과 공지",
                    "category": "수강",
                    "posted_at": datetime.date(2026, 6, 2),
                    "start_date": None,
                    "end_date": None,
                    "summary": "요약문",
                    "body_content": "가" * (mcp_mod._EVIDENCE_TEXT_LIMIT + 1),
                    "attachment_names": ["안내.pdf"],
                    "matched_chunk": "수강 철회 근거",
                    "vector_score": 0.87,
                    "rerank_score": 0.96,
                    "private_db_value": "노출 금지",
                }
            ],
            "evidence_chunks": [
                {
                    "url": "https://x/9",
                    "title": "검색결과 공지",
                    "category": "수강",
                    "content": "수강 철회 근거",
                    "vector_score": 0.87,
                    "rerank_score": 0.96,
                    "private_db_value": "노출 금지",
                }
            ],
        }

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(mcp_mod, "retrieve_mcp_evidence", fake_retrieve)
    with TestClient(app) as client:
        result = _tool_call_result(
            client, "unit-mcp-token", "search_knu_notices", {"query": "수강 철회", "limit": 99}
        )

    legacy = json.loads(result["content"][0]["text"])
    assert list(legacy[0]) == [
        "url", "title", "snippet", "score", "posted_at", "start_date", "end_date", "category", "summary",
    ]
    assert legacy[0]["url"] == "https://x/9"
    assert legacy[0]["score"] == 0.96

    package = result["structuredContent"]
    assert package["schema_version"] == 2
    assert package["status"] == "ok"
    assert package["query_mode"] == "precise"
    assert package["expanded_query"] == "2026학년도 수강 철회 신청 기간"
    assert package["categories"] == ["수강"]
    assert package["evidence_chunks"] == [
        {
            "url": "https://x/9",
            "title": "검색결과 공지",
            "category": "수강",
            "content": "수강 철회 근거",
            "vector_score": 0.87,
            "rerank_score": 0.96,
        }
    ]
    assert len(package["documents"][0]["body_content"]) <= mcp_mod._EVIDENCE_TEXT_LIMIT
    assert package["documents"][0]["truncated"] is True
    assert "private_db_value" not in json.dumps(package, ensure_ascii=False)


@pytest.mark.parametrize(
    ("query_mode", "contexts", "expected_status"),
    [
        ("smalltalk", [], "search_not_required"),
        ("precise", [], "no_results"),
        (
            "broad",
            [
                {
                    "url": "https://x/broad",
                    "title": "수강 공지 목록",
                    "category": "수강",
                    "matched_chunk": "여러 수강 공지 요약",
                    "vector_score": 0.7,
                    "rerank_score": 0.8,
                }
            ],
            "ok",
        ),
    ],
)
def test_search_knu_notices_returns_mode_status(monkeypatch, query_mode, contexts, expected_status):
    import api.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(
        mcp_mod,
        "retrieve_mcp_evidence",
        lambda query, major, category: {
            "query_mode": query_mode,
            "original_query": query,
            "expanded_query": query,
            "categories": [],
            "routing_fallback": False,
            "contexts": contexts,
            "evidence_chunks": [],
        },
    )

    with TestClient(app) as client:
        result = _tool_call_result(
            client,
            "unit-mcp-token",
            "search_knu_notices",
            {"query": "질문"},
        )

    assert result["structuredContent"]["status"] == expected_status
    assert result["structuredContent"]["query_mode"] == query_mode


def test_get_knu_notice_detail_limits_content_and_returns_source_url(monkeypatch):
    import api.mcp_server as mcp_mod

    content = "가" * (mcp_mod._DETAIL_CONTENT_LIMIT + 1)
    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(mcp_mod, "get_document_content", lambda category, url: content)
    with TestClient(app) as client:
        result = _tool_call(
            client,
            "unit-mcp-token",
            "get_knu_notice_detail",
            {"category": "학사", "url": "https://x/9"},
        )

    assert result == {
        "content": "가" * mcp_mod._DETAIL_CONTENT_LIMIT,
        "url": "https://x/9",
        "truncated": True,
    }
