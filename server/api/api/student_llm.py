"""학생 개인 대화 계정. 학교 공용 모델 설정이나 Codex 계정 파일을 읽지 않는다."""
from __future__ import annotations

import json
from hashlib import sha256
from uuid import UUID, uuid4

import httpx

from api.codex_oauth import (
    CODEX_CLIENT_ID, CODEX_ISSUER, CODEX_MODELS_URL, CODEX_TOKEN_URL,
    CODEX_FALLBACK_MODELS, _codex_headers, _decode_jwt, _jwt_expires_soon,
)
from api.crypto import decrypt_secret, encrypt_secret
from db.pool import pool


def _public(row: tuple) -> dict:
    return {
        "id": str(row[0]), "provider": row[1], "label": row[2],
        "model": row[3], "active": row[4],
    }


async def list_accounts(student_id: str) -> list[dict]:
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            "SELECT id,provider,label,model,active FROM student_llm_account "
            "WHERE student_id=%s ORDER BY created_at", (student_id,)
        )).fetchall()
    return [_public(row) for row in rows]


async def get_account(student_id: str, account_id: str | None = None) -> dict | None:
    async with pool.connection() as conn:
        if account_id:
            row = await (await conn.execute(
                "SELECT id,provider,label,model,active,encrypted_secret FROM student_llm_account "
                "WHERE student_id=%s AND id=%s", (student_id, UUID(account_id))
            )).fetchone()
        else:
            row = await (await conn.execute(
                "SELECT id,provider,label,model,active,encrypted_secret FROM student_llm_account "
                "WHERE student_id=%s AND active=TRUE", (student_id,)
            )).fetchone()
    if not row:
        return None
    return {**_public(row), "secret": json.loads(decrypt_secret(row[5]))}


async def save_account(student_id: str, provider: str, label: str, secret: dict,
                       model: str = "", account_id: str | None = None) -> dict:
    credential_identity = (secret.get("api_key") if provider in {"openai", "google"}
                           else secret.get("account_id"))
    if not credential_identity:
        raise ValueError("계정 식별 정보가 없습니다.")
    fingerprint = sha256(f"{provider}:{credential_identity}".encode()).hexdigest()
    identity = UUID(account_id) if account_id else uuid4()
    encrypted = encrypt_secret(json.dumps(secret))
    async with pool.connection() as conn:
        async with conn.transaction():
            duplicate = await (await conn.execute(
                "SELECT id,student_id,model FROM student_llm_account "
                "WHERE credential_fingerprint=%s", (fingerprint,),
            )).fetchone()
            if duplicate:
                if duplicate[1] != student_id:
                    raise ValueError("이미 다른 학생 계정에 연결된 LLM 계정입니다.")
                identity = duplicate[0]
                model = model or duplicate[2]
            if account_id:
                owned = await (await conn.execute(
                    "SELECT 1 FROM student_llm_account WHERE student_id=%s AND id=%s",
                    (student_id, identity),
                )).fetchone()
                if not owned:
                    raise LookupError("계정을 찾을 수 없습니다.")
            await conn.execute(
                "UPDATE student_llm_account SET active=FALSE WHERE student_id=%s AND active=TRUE",
                (student_id,),
            )
            await conn.execute(
                "INSERT INTO student_llm_account(id,student_id,provider,label,encrypted_secret,credential_fingerprint,model,active) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,TRUE) ON CONFLICT(id) DO UPDATE SET "
                "label=EXCLUDED.label,encrypted_secret=EXCLUDED.encrypted_secret,"
                "credential_fingerprint=EXCLUDED.credential_fingerprint,"
                "model=EXCLUDED.model,active=TRUE,updated_at=now() "
                "WHERE student_llm_account.student_id=EXCLUDED.student_id",
                (identity, student_id, provider, label, encrypted, fingerprint, model),
            )
    return {"id": str(identity), "provider": provider, "label": label, "model": model, "active": True}


async def select_account(student_id: str, account_id: str, model: str) -> dict:
    identity = UUID(account_id)
    async with pool.connection() as conn:
        async with conn.transaction():
            row = await (await conn.execute(
                "SELECT id,provider,label,model,active FROM student_llm_account "
                "WHERE student_id=%s AND id=%s", (student_id, identity)
            )).fetchone()
            if not row:
                raise LookupError("계정을 찾을 수 없습니다.")
            await conn.execute("UPDATE student_llm_account SET active=FALSE WHERE student_id=%s AND active=TRUE", (student_id,))
            await conn.execute(
                "UPDATE student_llm_account SET active=TRUE,model=%s,updated_at=now() "
                "WHERE student_id=%s AND id=%s", (model, student_id, identity),
            )
    return {**_public(row), "model": model, "active": True}


async def delete_account(student_id: str, account_id: str) -> bool:
    async with pool.connection() as conn:
        result = await conn.execute(
            "DELETE FROM student_llm_account WHERE student_id=%s AND id=%s",
            (student_id, UUID(account_id)),
        )
    return result.rowcount > 0


async def refresh_codex(student_id: str, account: dict) -> dict:
    secret = account["secret"]
    if not _jwt_expires_soon(str(secret.get("access_token") or "")):
        return account
    refresh_token = str(secret.get("refresh_token") or "")
    if not refresh_token:
        raise LookupError("Codex 재로그인이 필요합니다.")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(CODEX_TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": CODEX_CLIENT_ID,
        })
        response.raise_for_status()
        tokens = response.json()
    secret["access_token"] = tokens["access_token"]
    secret["refresh_token"] = tokens.get("refresh_token") or refresh_token
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE student_llm_account SET encrypted_secret=%s,updated_at=now() "
            "WHERE student_id=%s AND id=%s",
            (encrypt_secret(json.dumps(secret)), student_id, UUID(account["id"])),
        )
    return {**account, "secret": secret}


async def models_for_account(student_id: str, account_id: str) -> list[str]:
    account = await get_account(student_id, account_id)
    if not account:
        raise LookupError("계정을 찾을 수 없습니다.")
    async with httpx.AsyncClient(timeout=15) as client:
        if account["provider"] == "openai":
            response = await client.get("https://api.openai.com/v1/models", headers={
                "Authorization": f"Bearer {account['secret']['api_key']}"})
            response.raise_for_status()
            return sorted({item["id"] for item in response.json().get("data", [])
                           if str(item.get("id") or "").startswith(("gpt-", "o"))})
        if account["provider"] == "google":
            response = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                        headers={"x-goog-api-key": account["secret"]["api_key"]})
            response.raise_for_status()
            return sorted({str(item.get("name") or "").removeprefix("models/")
                           for item in response.json().get("models", [])
                           if isinstance(item, dict)
                           and "generateContent" in (item.get("supportedGenerationMethods") or [])
                           and str(item.get("name") or "").startswith("models/gemini-")})
        account = await refresh_codex(student_id, account)
        response = await client.get(CODEX_MODELS_URL, headers=_codex_headers(account["secret"]))
        response.raise_for_status()
        models = [str(item.get("slug")) for item in response.json().get("models", [])
                  if item.get("slug") and str(item.get("visibility") or "").lower() not in {"hide", "hidden"}]
        return list(dict.fromkeys(models)) or list(CODEX_FALLBACK_MODELS)


def codex_secret(tokens: dict) -> tuple[str, dict]:
    access = str(tokens.get("access_token") or "")
    if not access:
        raise ValueError("Codex access token이 없습니다.")
    claims = _decode_jwt(access)
    id_claims = _decode_jwt(str(tokens.get("id_token") or ""))
    auth = claims.get("https://api.openai.com/auth") or id_claims.get("https://api.openai.com/auth") or {}
    email = str(id_claims.get("email") or claims.get("email") or "")
    secret = {"access_token": access, "refresh_token": str(tokens.get("refresh_token") or ""),
              "account_id": str(auth.get("chatgpt_account_id") or "")}
    if not secret["account_id"]:
        raise ValueError("Codex 계정 식별 정보를 확인하지 못했습니다.")
    return email or "OpenAI Codex", secret
