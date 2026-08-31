import datetime
import json

import pytest
from fastapi.testclient import TestClient

from api.deps import create_portal_access_token
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
def test_mcp_accepts_internal_or_user_bearer_token(monkeypatch, token, expected_status):
    import interfaces.mcp.server as mcp_mod

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


def test_mcp_accepts_portal_login_token_without_static_secret(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", None)
    token = create_portal_access_token("20260001")
    with TestClient(app) as client:
        response = _mcp_request(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            token,
        )

    assert response.status_code == 200


def test_mcp_rate_limit_is_scoped_to_authenticated_principal(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    seen = []

    def fake_allow(key, limit):
        seen.append((key, limit))
        return len(seen) == 1

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", None)
    monkeypatch.setattr(mcp_mod, "allow_rate_limited_request", fake_allow)
    first_session = create_portal_access_token("20260002")
    second_session = create_portal_access_token("20260002")
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
        first = _mcp_request(client, payload, first_session)
        limited = _mcp_request(client, payload, second_session)

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert len({key for key, _ in seen}) == 1
    assert all(limit == mcp_mod.RATE_LIMIT_MCP for _, limit in seen)


def test_mcp_lists_only_notice_evidence_tools(monkeypatch):
    import interfaces.mcp.server as mcp_mod

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
        "knu_list_notices",
        "knu_search_notice_details",
        "knu_get_notice_detail",
    }
    scan_tool = next(tool for tool in tools if tool["name"] == "knu_list_notices")
    deep_tool = next(tool for tool in tools if tool["name"] == "knu_search_notice_details")
    assert "count" in scan_tool["description"]
    assert "reranking" in deep_tool["description"]
    assert "department" in deep_tool["inputSchema"]["properties"]
    assert "major" not in deep_tool["inputSchema"]["properties"]
    assert "limit" not in scan_tool["inputSchema"]["properties"]
    assert "limit" not in deep_tool["inputSchema"]["properties"]


def test_knu_list_notices_returns_server_total(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    seen = []

    def fake_list(*args):
        seen.append(args)
        return {
            "total": 4,
            "offset": 0,
            "returned": 1,
            "as_of": "2026-07-31",
            "time_scope": "current",
            "status": "open",
            "items": [{"id": 9, "title": "장학 공지"}],
        }

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(mcp_mod, "list_notices_for_scan", fake_list)
    with TestClient(app) as client:
        result = _tool_call(
            client,
            "unit-mcp-token",
            "knu_list_notices",
            {
                "category": "장학",
                "status": "open",
                "as_of": "2026-07-31",
                "sort": "end_date",
            },
        )

    assert result["total"] == 4
    assert result["items"][0]["title"] == "장학 공지"
    assert seen[0][0:4] == (
        "장학",
        "open",
        datetime.date(2026, 7, 31),
        "current",
    )


def test_mcp_automatically_scopes_scan_and_deep_to_student_profile(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    scan_calls = []
    deep_calls = []

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", None)
    monkeypatch.setattr(
        mcp_mod,
        "get_user",
        lambda student_id: {
            "student_id": student_id,
            "major": "컴퓨터공학과",
            "year": 3,
        },
    )

    def fake_list(*args):
        scan_calls.append(args)
        return {"total": 0, "items": []}

    def fake_retrieve(query, department, category, time_scope, year, notice_ids):
        deep_calls.append((query, department, category, time_scope, year, notice_ids))
        return {
            "query_mode": "deep",
            "original_query": query,
            "expanded_query": query,
            "categories": [],
            "department": department,
            "time_scope": time_scope,
            "year": year,
            "notice_ids": notice_ids or [],
            "routing_fallback": False,
            "contexts": [],
            "evidence_chunks": [],
        }

    monkeypatch.setattr(mcp_mod, "list_notices_for_scan", fake_list)
    monkeypatch.setattr(mcp_mod, "retrieve_mcp_evidence", fake_retrieve)
    token = create_portal_access_token("20260003")

    with TestClient(app) as client:
        scan = _tool_call(client, token, "knu_list_notices", {})
        deep = _tool_call_result(
            client,
            token,
            "knu_search_notice_details",
            {"query": "수강신청 절차"},
        )["structuredContent"]

    assert scan_calls[0][4:6] == ("컴퓨터공학과", 3)
    assert deep_calls[0][1] == "컴퓨터공학과"
    assert scan["personalization"] == {
        "department": "컴퓨터공학과",
        "grade": 3,
        "profile_department": "컴퓨터공학과",
        "profile_grade": 3,
        "automatic_department": True,
        "automatic_grade": True,
    }
    assert deep["department"] == "컴퓨터공학과"
    assert deep["personalization"]["profile_department"] == "컴퓨터공학과"


def test_knu_search_notice_details_returns_safe_fields(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    def fake_retrieve(query, department, category_override, time_scope, year, notice_ids):
        assert (query, department, category_override) == ("수강 철회", None, "수강")
        assert (time_scope, year, notice_ids) == ("current", 2026, None)
        return {
            "query_mode": "deep",
            "original_query": query,
            "expanded_query": "2026학년도 수강 철회 신청 기간",
            "categories": ["수강"],
            "time_scope": "current",
            "year": 2026,
            "notice_ids": [],
            "routing_fallback": False,
            "contexts": [
                {
                    "url": "https://x/9",
                    "title": "검색결과 공지",
                    "category": "수강",
                    "source_name": "컴퓨터공학과",
                    "source_department": "컴퓨터공학과",
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
                    "source_name": "컴퓨터공학과",
                    "source_department": "컴퓨터공학과",
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
            client,
            "unit-mcp-token",
            "knu_search_notice_details",
            {"query": "수강 철회", "category": "수강", "year": 2026},
        )

    legacy = json.loads(result["content"][0]["text"])
    assert list(legacy[0]) == [
        "url", "title", "snippet", "score", "posted_at", "start_date", "end_date",
        "category", "source_name", "source_department", "summary",
    ]
    assert legacy[0]["url"] == "https://x/9"
    assert legacy[0]["score"] == 0.96

    package = result["structuredContent"]
    assert package["schema_version"] == 2
    assert package["status"] == "ok"
    assert package["query_mode"] == "deep"
    assert package["expanded_query"] == "2026학년도 수강 철회 신청 기간"
    assert package["categories"] == ["수강"]
    assert package["time_scope"] == "current"
    assert package["year"] == 2026
    assert package["evidence_chunks"] == [
        {
            "url": "https://x/9",
            "title": "검색결과 공지",
            "category": "수강",
            "source_name": "컴퓨터공학과",
            "source_department": "컴퓨터공학과",
            "content": "수강 철회 근거",
            "vector_score": 0.87,
            "rerank_score": 0.96,
        }
    ]
    assert len(package["documents"][0]["body_content"]) <= mcp_mod._EVIDENCE_TEXT_LIMIT
    assert package["documents"][0]["source_department"] == "컴퓨터공학과"
    assert package["documents"][0]["truncated"] is True
    assert "private_db_value" not in json.dumps(package, ensure_ascii=False)


@pytest.mark.parametrize(
    ("contexts", "expected_status"),
    [
        ([], "no_results"),
        (
            [
                {
                    "url": "https://x/deep",
                    "title": "수강 공지 근거",
                    "category": "수강",
                    "matched_chunk": "수강 공지 상세",
                    "vector_score": 0.7,
                    "rerank_score": 0.8,
                }
            ],
            "ok",
        ),
    ],
)
def test_knu_search_notice_details_returns_status(monkeypatch, contexts, expected_status):
    import interfaces.mcp.server as mcp_mod

    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(
        mcp_mod,
        "retrieve_mcp_evidence",
        lambda query, department, category, time_scope, year, notice_ids: {
            "query_mode": "deep",
            "original_query": query,
            "expanded_query": query,
            "categories": [],
            "time_scope": time_scope,
            "year": year,
            "notice_ids": notice_ids or [],
            "routing_fallback": False,
            "contexts": contexts,
            "evidence_chunks": [],
        },
    )

    with TestClient(app) as client:
        result = _tool_call_result(
            client,
            "unit-mcp-token",
            "knu_search_notice_details",
            {"query": "질문"},
        )

    assert result["structuredContent"]["status"] == expected_status
    assert result["structuredContent"]["query_mode"] == "deep"


def test_get_knu_notice_detail_limits_content_and_returns_source_url(monkeypatch):
    import interfaces.mcp.server as mcp_mod

    content = "가" * (mcp_mod._DETAIL_CONTENT_LIMIT + 1)
    monkeypatch.setattr(mcp_mod, "MCP_AUTH_TOKEN", "unit-mcp-token")
    monkeypatch.setattr(mcp_mod, "get_document_content", lambda url: content)
    with TestClient(app) as client:
        result = _tool_call(
            client,
            "unit-mcp-token",
            "knu_get_notice_detail",
            {"url": "https://x/9"},
        )

    assert result == {
        "content": "가" * mcp_mod._DETAIL_CONTENT_LIMIT,
        "url": "https://x/9",
        "truncated": True,
    }
