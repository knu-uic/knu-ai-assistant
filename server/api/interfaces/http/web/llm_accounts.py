"""학생 본인의 대화 모델 연결 API. 요청 본문에서 학번을 받지 않는다."""
from __future__ import annotations

import time
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.codex_oauth import CODEX_CLIENT_ID, CODEX_ISSUER, CODEX_TOKEN_URL
from api.deps import portal_student_id, require_user
from api.student_llm import (
    codex_secret, delete_account, get_account, list_accounts,
    models_for_account, save_account, select_account,
)

router = APIRouter()
_login_sessions: dict[str, dict] = {}


def _student(principal: str = Depends(require_user)) -> str:
    student_id = portal_student_id(principal)
    if not student_id:
        raise HTTPException(403, "학생 계정이 필요합니다.")
    return student_id


class ApiKeyRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=500)


class SelectionRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)


@router.get("/me/llm/accounts")
async def accounts(student_id: str = Depends(_student)) -> dict:
    return {"items": await list_accounts(student_id)}


@router.post("/me/llm/openai-key")
async def add_openai_key(req: ApiKeyRequest, student_id: str = Depends(_student)) -> dict:
    key = req.api_key.strip()
    if not key.startswith("sk-"):
        raise HTTPException(422, "OpenAI API 키 형식이 아닙니다.")
    try:
        return await save_account(student_id, "openai", "OpenAI API", {"api_key": key})
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/me/llm/google-key")
async def add_google_key(req: ApiKeyRequest, student_id: str = Depends(_student)) -> dict:
    try:
        return await save_account(student_id, "google", "Gemini API",
                                  {"api_key": req.api_key.strip()})
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/me/llm/codex/login")
async def start_codex_login(student_id: str = Depends(_student)) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode",
                                     json={"client_id": CODEX_CLIENT_ID})
        response.raise_for_status()
        payload = response.json()
    session_id = uuid4().hex
    _login_sessions[session_id] = {
        "student_id": student_id, "device_auth_id": payload["device_auth_id"],
        "user_code": payload["user_code"], "expires_at": time.time() + 900,
        "interval": max(3, int(payload.get("interval") or 5)), "last_poll": 0.0,
    }
    return {"id": session_id, "user_code": payload["user_code"],
            "verification_url": f"{CODEX_ISSUER}/codex/device",
            "interval": _login_sessions[session_id]["interval"]}


@router.get("/me/llm/codex/login/{session_id}")
async def poll_codex_login(session_id: str, student_id: str = Depends(_student)) -> dict:
    session = _login_sessions.get(session_id)
    if not session or session["student_id"] != student_id:
        raise HTTPException(404, "로그인 요청을 찾을 수 없습니다.")
    now = time.time()
    if now >= session["expires_at"]:
        _login_sessions.pop(session_id, None)
        return {"status": "expired"}
    if now - session["last_poll"] < session["interval"]:
        return {"status": "pending"}
    session["last_poll"] = now
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"{CODEX_ISSUER}/api/accounts/deviceauth/token",
                                     json={"device_auth_id": session["device_auth_id"],
                                           "user_code": session["user_code"]})
        if response.status_code in {403, 404}:
            return {"status": "pending"}
        response.raise_for_status()
        code = response.json()
        token_response = await client.post(CODEX_TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code["authorization_code"],
            "redirect_uri": f"{CODEX_ISSUER}/deviceauth/callback",
            "client_id": CODEX_CLIENT_ID, "code_verifier": code["code_verifier"],
        })
        token_response.raise_for_status()
        try:
            label, secret = codex_secret(token_response.json())
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from exc
    # 같은 로그인 요청을 다른 학생이 소비할 수 없다.
    _login_sessions.pop(session_id, None)
    try:
        account = await save_account(student_id, "openai-codex", label, secret)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "approved", "account": account}


@router.get("/me/llm/accounts/{account_id}/models")
async def account_models(account_id: UUID, student_id: str = Depends(_student)) -> dict:
    try:
        return {"models": await models_for_account(student_id, str(account_id))}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/me/llm/accounts/{account_id}/selection")
async def account_selection(account_id: UUID, req: SelectionRequest,
                            student_id: str = Depends(_student)) -> dict:
    try:
        available = await models_for_account(student_id, str(account_id))
        if req.model not in available:
            raise HTTPException(422, "이 계정에서 사용할 수 없는 모델입니다.")
        return await select_account(student_id, str(account_id), req.model)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/me/llm/accounts/{account_id}")
async def remove_account(account_id: UUID, student_id: str = Depends(_student)) -> dict:
    if not await delete_account(student_id, str(account_id)):
        raise HTTPException(404, "계정을 찾을 수 없습니다.")
    return {"deleted": True}
