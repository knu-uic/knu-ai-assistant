import datetime
import json

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
    return json.loads(response.json()["result"]["content"][0]["text"])


def test_mcp_requires_bearer_token_before_initialize():
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

    with TestClient(app) as client:
        response = _mcp_request(client, payload)

    assert response.status_code == 401


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
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
        "search_knu_notices",
        "get_knu_notice_detail",
    }


def test_search_knu_notices_returns_only_safe_search_fields(monkeypatch):
    import api.mcp_server as mcp_mod

    fake_rows = [(
        "https://x/9", "검색결과 공지", "스니펫 본문", 0.87,
        datetime.date(2026, 6, 2), None, None,
        "학사", ["전체"], ["수강"],
        "KNU", "학사과", "notice", None, "요약문", "비공개 본문", ["비공개.pdf"],
    )]

    async def fake_search(**kwargs):
        assert kwargs == {"q": "수강 철회", "major": None, "category": None, "limit": 10}
        from api.mappers import result_from_search_row
        return [result_from_search_row(row) for row in fake_rows]

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(mcp_mod, "search_notice_results", fake_search)
    with TestClient(app) as client:
        result = _tool_call(
            client, "unit-mcp-token", "search_knu_notices", {"query": "수강 철회", "limit": 99}
        )

    assert list(result[0]) == [
        "url", "title", "snippet", "score", "posted_at", "start_date", "end_date", "category", "summary",
    ]
    assert result[0]["url"] == "https://x/9"
    assert result[0]["summary"] == "요약문"


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
