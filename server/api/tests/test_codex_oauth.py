import base64
import asyncio
import json
import time

import httpx

from api import codex_oauth


def _jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def test_token_store_is_private_and_supports_account_selection(tmp_path, monkeypatch):
    path = tmp_path / "codex-auth.json"
    monkeypatch.setenv("KNU_CODEX_AUTH_PATH", str(path))
    first = codex_oauth._save_tokens({
        "access_token": _jwt({"email": "first@example.com", "exp": time.time() + 3600}),
        "refresh_token": "refresh-1",
    })
    second = codex_oauth._save_tokens({
        "access_token": _jwt({"email": "second@example.com", "exp": time.time() + 3600}),
        "refresh_token": "refresh-2",
    })
    accounts = codex_oauth.list_accounts()
    assert len(accounts) == 2
    assert accounts[0]["active"] is True
    assert "access_token" not in accounts[0]
    codex_oauth.select_account(first["id"])
    assert codex_oauth.active_account(refresh=False)["id"] == first["id"]
    assert codex_oauth.remove_account(second["id"]) is True
    assert path.stat().st_mode & 0o777 == 0o600


def test_device_login_flow_saves_only_sanitized_public_account(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_CODEX_AUTH_PATH", str(tmp_path / "codex-auth.json"))
    codex_oauth._SESSIONS.clear()
    access = _jwt({
        "email": "student@example.com",
        "exp": time.time() + 3600,
        "https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"},
    })

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/usercode"):
            return httpx.Response(200, json={"user_code": "ABCD-EFGH", "device_auth_id": "dev-1", "interval": 3})
        if request.url.path.endswith("/deviceauth/token"):
            return httpx.Response(200, json={"authorization_code": "code", "code_verifier": "verifier"})
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": access, "refresh_token": "secret-refresh"})
        return httpx.Response(404)

    async def run_flow():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            session = await codex_oauth.start_login(client)
            codex_oauth._SESSIONS[session["id"]]["last_poll"] = 0
            return await codex_oauth.poll_login(session["id"], client)

    approved = asyncio.run(run_flow())
    assert approved["status"] == "approved"
    assert approved["account"]["email"] == "student@example.com"
    assert approved["account"]["account_id"] == "acct-123"
    assert "access_token" not in approved["account"]


def test_codex_response_parses_streamed_text(tmp_path, monkeypatch):
    monkeypatch.setenv("KNU_CODEX_AUTH_PATH", str(tmp_path / "codex-auth.json"))
    codex_oauth._save_tokens({
        "access_token": _jwt({"exp": time.time() + 3600}),
        "refresh_token": "refresh",
    })

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["originator"] == "codex_cli_rs"
        body = json.loads(request.content)
        assert body["input"][0]["content"][1]["type"] == "input_image"
        stream = 'data: {"type":"response.output_text.delta","delta":"표 "}\n\ndata: {"type":"response.output_text.delta","delta":"추출"}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = codex_oauth.codex_response("표를 추출해", model="gpt-5.6-sol", image_data_url="data:image/png;base64,AA==", client=client)
    assert result == "표 추출"
