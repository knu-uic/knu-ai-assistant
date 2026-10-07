import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from api.deps import create_portal_access_token
from api.main import app


@pytest.mark.real_auth
def test_chat_uses_only_authenticated_students_account(monkeypatch):
    import interfaces.http.web.chat as chat

    looked_up = []
    called_with = []

    async def account(student_id, account_id=None):
        looked_up.append(student_id)
        return {"id": student_id, "provider": "openai", "model": "test-model",
                "secret": {"api_key": f"key-{student_id}"}}

    async def catalog():
        return [], {}

    async def response(client, account, inputs, definitions):
        called_with.append(account["secret"]["api_key"])
        return {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "ok"}]}]}

    monkeypatch.setattr(chat, "get_account", account)
    monkeypatch.setattr(chat, "_tool_catalog", catalog)
    monkeypatch.setattr(chat, "_response", response)
    with TestClient(app) as client:
        for student in ("20260001", "20260002"):
            token = create_portal_access_token(student)
            result = client.post("/api/chat", json={"question": "test"},
                                 headers={"Authorization": f"Bearer {token}"})
            assert result.status_code == 200
            assert result.json()["answer"] == "ok"
    assert looked_up == ["20260001", "20260002"]
    assert called_with == ["key-20260001", "key-20260002"]


@pytest.mark.real_auth
def test_chat_does_not_fall_back_to_school_account(monkeypatch):
    import interfaces.http.web.chat as chat

    async def missing(student_id, account_id=None):
        return None

    monkeypatch.setattr(chat, "get_account", missing)
    with TestClient(app) as client:
        token = create_portal_access_token("20260001")
        result = client.post("/api/chat", json={"question": "test"},
                             headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 409


def test_tool_call_is_bound_to_current_student(monkeypatch):
    import interfaces.http.web.chat as chat
    from interfaces.mcp.server import _MCP_PRINCIPAL

    principals = []

    class Tool:
        async def run(self, arguments):
            principals.append(_MCP_PRINCIPAL.get())
            return type("Result", (), {"structured_content": {"ok": True}})()

    async def account(student_id, account_id=None):
        return {"id": student_id, "provider": "openai", "model": "test-model",
                "secret": {"api_key": "personal"}}

    async def catalog():
        return [{"type": "function", "name": "read", "parameters": {"type": "object"}}], {"read": Tool()}

    responses = [
        {"output": [{"type": "function_call", "name": "read", "call_id": "call-1", "arguments": "{}"}]},
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]},
    ]

    async def response(client, account, inputs, definitions):
        return responses.pop(0)

    monkeypatch.setattr(chat, "get_account", account)
    monkeypatch.setattr(chat, "_tool_catalog", catalog)
    monkeypatch.setattr(chat, "_response", response)
    result = asyncio.run(chat.answer("20260001", "test", []))
    assert result == "ok"
    assert principals == ["portal:20260001"]
    assert _MCP_PRINCIPAL.get() is None


@pytest.mark.real_auth
def test_codex_login_session_cannot_be_polled_by_another_student():
    import interfaces.http.web.llm_accounts as accounts

    accounts._login_sessions["owner-session"] = {
        "student_id": "20260001", "expires_at": 9999999999,
        "interval": 5, "last_poll": 0,
    }
    try:
        with TestClient(app) as client:
            token = create_portal_access_token("20260002")
            result = client.get("/api/me/llm/codex/login/owner-session",
                                headers={"Authorization": f"Bearer {token}"})
        assert result.status_code == 404
    finally:
        accounts._login_sessions.pop("owner-session", None)


def test_web_tool_catalog_excludes_submission_tool():
    import interfaces.http.web.chat as chat

    definitions, allowed = asyncio.run(chat._tool_catalog())
    names = {item["name"] for item in definitions}
    assert "knu_search_notice_details" in names
    assert "knu_prepare_online_counseling" in names
    assert "knu_submit_online_counseling" not in names
    assert "knu_submit_online_counseling" not in allowed


def test_codex_stream_uses_text_deltas_when_completed_output_is_empty():
    import interfaces.http.web.chat as chat

    events = [
        {"type": "response.output_text.delta", "delta": "안녕"},
        {"type": "response.output_text.delta", "delta": "하세요"},
        {"type": "response.completed", "response": {"output": []}},
    ]

    def handler(request):
        body = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await chat._response(client, {
                "provider": "openai-codex", "model": "test-model",
                "secret": {"access_token": "test-token"},
            }, [{"role": "user", "content": "안녕"}], [])
        return chat._answer_text(response)

    assert asyncio.run(run()) == "안녕하세요"


def test_chat_rejects_empty_model_answer(monkeypatch):
    import interfaces.http.web.chat as chat

    async def account(student_id, account_id=None):
        return {"provider": "openai", "model": "test-model",
                "secret": {"api_key": "personal"}}

    async def catalog():
        return [], {}

    async def response(client, account, inputs, definitions):
        return {"output": []}

    monkeypatch.setattr(chat, "get_account", account)
    monkeypatch.setattr(chat, "_tool_catalog", catalog)
    monkeypatch.setattr(chat, "_response", response)
    with pytest.raises(RuntimeError, match="빈 답변"):
        asyncio.run(chat.answer("20260001", "안녕", []))


def test_school_chat_uses_local_model_and_student_bound_tools(monkeypatch):
    import interfaces.http.web.chat as chat
    from interfaces.mcp.server import _MCP_PRINCIPAL

    seen = []
    principals = []

    class Tool:
        async def run(self, arguments):
            principals.append(_MCP_PRINCIPAL.get())
            return type("Result", (), {"structured_content": {"ok": True}})()

    async def catalog():
        return [{"name": "read", "description": "Read", "parameters": {"type": "object"}}], {"read": Tool()}

    def handler(request):
        seen.append((str(request.url), request.headers.get("Authorization"), json.loads(request.content)))
        if len(seen) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }]}
        else:
            message = {"role": "assistant", "content": "학교 모델 답변"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(chat.httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs))
    monkeypatch.setattr(chat, "_school_settings", lambda: {
        "enabled": True, "provider": "ollama", "model": "school-local",
        "base_url": "http://127.0.0.1:11434/v1",
    })
    monkeypatch.setattr(chat, "_tool_catalog", catalog)

    result = asyncio.run(chat.school_answer("20260001", "안녕", []))
    assert result == "학교 모델 답변"
    assert principals == ["portal:20260001"]
    assert _MCP_PRINCIPAL.get() is None
    assert len(seen) == 2
    assert all(url == "http://127.0.0.1:11434/v1/chat/completions" for url, _, _ in seen)
    assert all(auth == "Bearer local" for _, auth, _ in seen)
    assert seen[1][2]["messages"][-1]["tool_call_id"] == "call-1"


@pytest.mark.real_auth
def test_chat_school_selection_does_not_use_personal_account(monkeypatch):
    import interfaces.http.web.chat as chat

    students = []

    async def school(student_id, question, history):
        students.append(student_id)
        return "학교 답변"

    async def personal(student_id, question, history):
        raise AssertionError("개인 모델을 호출하면 안 됩니다")

    monkeypatch.setattr(chat, "school_answer", school)
    monkeypatch.setattr(chat, "answer", personal)
    with TestClient(app) as client:
        token = create_portal_access_token("20260001")
        result = client.post("/api/chat", json={"question": "안녕", "source": "school"},
                             headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 200
    assert result.json() == {"answer": "학교 답변"}
    assert students == ["20260001"]


def test_school_chat_rejects_nonlocal_endpoint(monkeypatch):
    import interfaces.http.web.chat as chat

    monkeypatch.setattr(chat, "load_settings", lambda: {"school_chat": {
        "enabled": True, "provider": "ollama", "model": "school-model",
        "base_url": "https://external.example/v1",
    }})
    with pytest.raises(Exception, match="로컬 주소"):
        chat._school_settings()


def test_school_and_personal_gemini_use_separate_keys(monkeypatch):
    import interfaces.http.web.chat as chat

    used = []

    async def account(student_id, account_id=None):
        return {"provider": "google", "model": "personal-model",
                "secret": {"api_key": "personal-key"}}

    async def completion(student_id, question, history, settings):
        used.append((settings["model"], settings["api_key"]))
        return "ok"

    monkeypatch.setattr(chat, "get_account", account)
    monkeypatch.setattr(chat, "_chat_completions_answer", completion)
    monkeypatch.setattr(chat, "load_settings", lambda: {"school_chat": {
        "enabled": True, "provider": "google", "model": "school-model",
        "base_url": "", "api_key": "school-key",
    }})
    assert asyncio.run(chat.answer("20260001", "안녕", [])) == "ok"
    assert asyncio.run(chat.school_answer("20260001", "안녕", [])) == "ok"
    assert used == [("personal-model", "personal-key"), ("school-model", "school-key")]
