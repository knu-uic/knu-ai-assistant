"""KNU Server Manager용 OpenAI Codex OAuth 계정 저장소.

Codmes와 인증 파일을 공유하지 않는다. 이 서버에서 로그아웃해도
Codmes 클라이언트의 계정에는 영향을 주지 않기 위함이다.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

import httpx

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_ISSUER = "https://auth.openai.com"
CODEX_TOKEN_URL = f"{CODEX_ISSUER}/oauth/token"
CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models?client_version=1.0.0"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_FALLBACK_MODELS = (
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-5.5", "gpt-5.4", "gpt-5.4-mini",
)

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "codex-auth.json"
_LOCK = RLock()
_SESSIONS: dict[str, dict[str, Any]] = {}


def auth_path() -> Path:
    return Path(os.getenv("KNU_CODEX_AUTH_PATH", str(_DEFAULT_PATH))).expanduser()


def _read_store() -> dict:
    path = auth_path()
    with _LOCK:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
    accounts = raw.get("accounts") if isinstance(raw.get("accounts"), list) else []
    return {"version": 1, "active_id": str(raw.get("active_id") or ""), "accounts": accounts}


def _write_store(value: dict) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _public_account(account: dict, active_id: str) -> dict:
    return {
        "id": str(account.get("id") or ""),
        "label": str(account.get("label") or "OpenAI Codex"),
        "email": str(account.get("account_email") or ""),
        "account_id": str(account.get("account_id") or ""),
        "active": str(account.get("id") or "") == active_id,
        "added_at": account.get("added_at"),
    }


def list_accounts() -> list[dict]:
    store = _read_store()
    return [_public_account(item, store["active_id"]) for item in store["accounts"]]


def active_account(*, refresh: bool = True) -> dict:
    store = _read_store()
    account = next((item for item in store["accounts"] if item.get("id") == store["active_id"]), None)
    if account is None and store["accounts"]:
        account = store["accounts"][0]
    if account is None:
        raise LookupError("Codex에 로그인된 계정이 없습니다.")
    if refresh and _jwt_expires_soon(str(account.get("access_token") or "")):
        account = refresh_account(str(account["id"]))
    return account


def select_account(account_id: str) -> dict:
    store = _read_store()
    account = next((item for item in store["accounts"] if item.get("id") == account_id), None)
    if account is None:
        raise LookupError("계정을 찾을 수 없습니다.")
    store["active_id"] = account_id
    _write_store(store)
    return _public_account(account, account_id)


def remove_account(account_id: str) -> bool:
    store = _read_store()
    remaining = [item for item in store["accounts"] if item.get("id") != account_id]
    if len(remaining) == len(store["accounts"]):
        return False
    store["accounts"] = remaining
    if store["active_id"] == account_id:
        store["active_id"] = str(remaining[0].get("id") or "") if remaining else ""
    _write_store(store)
    return True


async def start_login(client: httpx.AsyncClient | None = None) -> dict:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode",
            json={"client_id": CODEX_CLIENT_ID},
            headers={"accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await client.aclose()
    user_code = str(payload.get("user_code") or "").strip()
    device_auth_id = str(payload.get("device_auth_id") or "").strip()
    if not user_code or not device_auth_id:
        raise RuntimeError("Codex 로그인 코드를 받지 못했습니다.")
    session_id = uuid.uuid4().hex
    now = time.time()
    _SESSIONS[session_id] = {
        "id": session_id,
        "status": "pending",
        "user_code": user_code,
        "device_auth_id": device_auth_id,
        "verification_url": f"{CODEX_ISSUER}/codex/device",
        "interval": max(3, int(payload.get("interval") or 5)),
        "last_poll": 0.0,
        "expires_at": now + 15 * 60,
        "error": "",
    }
    return _public_session(_SESSIONS[session_id])


async def poll_login(session_id: str, client: httpx.AsyncClient | None = None) -> dict:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise LookupError("로그인 요청을 찾을 수 없습니다.")
    if session["status"] != "pending":
        return _public_session(session)
    now = time.time()
    if now >= session["expires_at"]:
        session["status"] = "expired"
        return _public_session(session)
    if now - session["last_poll"] < session["interval"]:
        return _public_session(session)
    session["last_poll"] = now
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/token",
            json={"device_auth_id": session["device_auth_id"], "user_code": session["user_code"]},
            headers={"accept": "application/json"},
        )
        if response.status_code in {403, 404}:
            return _public_session(session)
        response.raise_for_status()
        code = response.json()
        token_response = await client.post(
            CODEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": str(code.get("authorization_code") or ""),
                "redirect_uri": f"{CODEX_ISSUER}/deviceauth/callback",
                "client_id": CODEX_CLIENT_ID,
                "code_verifier": str(code.get("code_verifier") or ""),
            },
            headers={"accept": "application/json", "user-agent": "knu-server-manager/0.1.0"},
        )
        token_response.raise_for_status()
        account = _save_tokens(token_response.json())
        session["status"] = "approved"
        session["account"] = _public_account(account, str(account["id"]))
    except httpx.HTTPError as exc:
        session["status"] = "error"
        session["error"] = f"Codex 로그인 처리 실패: {exc}"
    finally:
        if owns_client:
            await client.aclose()
    return _public_session(session)


def cancel_login(session_id: str) -> bool:
    session = _SESSIONS.get(session_id)
    if session is None:
        return False
    if session["status"] == "pending":
        session["status"] = "canceled"
    return True


def _save_tokens(tokens: dict) -> dict:
    access_token = str(tokens.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Codex OAuth가 access token을 반환하지 않았습니다.")
    id_token = str(tokens.get("id_token") or "").strip()
    claims = _decode_jwt(access_token)
    id_claims = _decode_jwt(id_token)
    auth_claims = claims.get("https://api.openai.com/auth") or id_claims.get("https://api.openai.com/auth") or {}
    email = str(tokens.get("email") or id_claims.get("email") or claims.get("email") or "").strip()
    account_id = str(tokens.get("account_id") or auth_claims.get("chatgpt_account_id") or "").strip()
    account = {
        "id": uuid.uuid4().hex[:12],
        "label": email or account_id or "OpenAI Codex",
        "access_token": access_token,
        "refresh_token": str(tokens.get("refresh_token") or ""),
        "id_token": id_token,
        "account_email": email,
        "account_id": account_id,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_cache": [],
    }
    store = _read_store()
    duplicate = next((item for item in store["accounts"] if account_id and item.get("account_id") == account_id), None)
    if duplicate:
        account["id"] = duplicate["id"]
        store["accounts"] = [account if item.get("id") == duplicate["id"] else item for item in store["accounts"]]
    else:
        store["accounts"].insert(0, account)
    store["active_id"] = account["id"]
    _write_store(store)
    return account


def refresh_account(account_id: str, client: httpx.Client | None = None) -> dict:
    store = _read_store()
    account = next((item for item in store["accounts"] if item.get("id") == account_id), None)
    if account is None:
        raise LookupError("계정을 찾을 수 없습니다.")
    refresh_token = str(account.get("refresh_token") or "")
    if not refresh_token:
        return account
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.post(
            CODEX_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CODEX_CLIENT_ID},
            headers={"accept": "application/json", "user-agent": "knu-server-manager/0.1.0"},
        )
        response.raise_for_status()
        tokens = response.json()
    finally:
        if owns_client:
            client.close()
    account["access_token"] = str(tokens.get("access_token") or account["access_token"])
    account["refresh_token"] = str(tokens.get("refresh_token") or refresh_token)
    if tokens.get("id_token"):
        account["id_token"] = str(tokens["id_token"])
    _write_store(store)
    return account


def discover_models(client: httpx.Client | None = None) -> dict:
    account = active_account()
    owns_client = client is None
    client = client or httpx.Client(timeout=12)
    models: list[str] = []
    source = "fallback"
    try:
        response = client.get(CODEX_MODELS_URL, headers=_codex_headers(account))
        response.raise_for_status()
        entries = response.json().get("models", [])
        visible = [item for item in entries if str(item.get("visibility") or "").lower() not in {"hide", "hidden"}]
        visible.sort(key=lambda item: (int(item.get("priority") or 10000), str(item.get("slug") or "")))
        models = list(dict.fromkeys(str(item.get("slug") or "").strip() for item in visible if item.get("slug")))
        if models:
            source = "live"
    except httpx.HTTPError:
        models = [str(item) for item in account.get("model_cache") or []]
        if models:
            source = "cache"
    finally:
        if owns_client:
            client.close()
    if not models:
        models = list(CODEX_FALLBACK_MODELS)
    account["model_cache"] = models
    store = _read_store()
    store["accounts"] = [account if item.get("id") == account.get("id") else item for item in store["accounts"]]
    _write_store(store)
    return {"source": source, "models": models}


def codex_response(prompt: str, *, model: str, image_data_url: str | None = None, client: httpx.Client | None = None) -> str:
    account = active_account()
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    if image_data_url:
        content.append({"type": "input_image", "image_url": image_data_url})
    body = {
        "model": model,
        "instructions": "Answer accurately. Return only the requested result without hidden reasoning.",
        "input": [{"role": "user", "content": content}],
        "store": False,
        "stream": True,
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=180)
    try:
        with client.stream("POST", CODEX_RESPONSES_URL, headers={**_codex_headers(account), "accept": "text/event-stream"}, json=body) as response:
            response.raise_for_status()
            parts: list[str] = []
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response.output_text.delta":
                    parts.append(str(event.get("delta") or ""))
                elif event.get("type") == "response.completed" and not parts:
                    parts.append(_completed_text(event.get("response") or {}))
            return "".join(parts).strip()
    finally:
        if owns_client:
            client.close()


def _completed_text(response: dict) -> str:
    parts: list[str] = []
    for output in response.get("output") or []:
        for item in output.get("content") or []:
            if item.get("type") == "output_text":
                parts.append(str(item.get("text") or ""))
    return "".join(parts)


def _codex_headers(account: dict) -> dict:
    headers = {
        "authorization": f"Bearer {account['access_token']}",
        "content-type": "application/json",
        "user-agent": "codex_cli_rs/0.0.0 (KNU Server Manager)",
        "originator": "codex_cli_rs",
    }
    account_id = str(account.get("account_id") or "")
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def _public_session(session: dict) -> dict:
    return {
        "id": session["id"], "status": session["status"],
        "user_code": session["user_code"], "verification_url": session["verification_url"],
        "interval": session["interval"], "expires_at": session["expires_at"],
        "account": session.get("account"), "error": session.get("error") or "",
    }


def _decode_jwt(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (IndexError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _jwt_expires_soon(token: str, leeway: int = 120) -> bool:
    expiry = _decode_jwt(token).get("exp")
    return bool(expiry and float(expiry) <= time.time() + leeway)
