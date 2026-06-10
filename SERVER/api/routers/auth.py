import secrets
from datetime import datetime, timedelta, timezone
from functools import partial

import anyio
import bcrypt
from fastapi import APIRouter, HTTPException

from api.deps import create_access_token
from api.mailer import send_verification_email
from api.schemas.auth import (
    LoginRequest,
    SignupCodeRequest,
    SignupVerifyRequest,
    TokenResponse,
)
from config import SIGNUP_EMAIL_DOMAIN
from db.accounts import (
    consume_verification,
    create_account,
    get_account,
    insert_verification,
    last_verification_at,
)

router = APIRouter()

RESEND_COOLDOWN_SECONDS = 60
CODE_TTL_MINUTES = 10


@router.post("/auth/signup/request")
async def signup_request(req: SignupCodeRequest) -> dict:
    email = req.email.strip().lower()
    if email.count("@") != 1 or not email.endswith(f"@{SIGNUP_EMAIL_DOMAIN}"):
        raise HTTPException(
            status_code=400,
            detail=f"학교 메일(@{SIGNUP_EMAIL_DOMAIN})로만 가입할 수 있습니다.",
        )

    last = await anyio.to_thread.run_sync(partial(last_verification_at, email))
    now = datetime.now(timezone.utc)
    if last is not None and (now - last).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=429,
            detail="인증 코드를 이미 보냈습니다. 1분 후 다시 시도해주세요. 메일이 없으면 스팸함을 확인해주세요.",
        )

    code = f"{secrets.randbelow(10**6):06d}"
    await anyio.to_thread.run_sync(
        partial(insert_verification, email, code, now + timedelta(minutes=CODE_TTL_MINUTES))
    )
    try:
        await anyio.to_thread.run_sync(partial(send_verification_email, email, code))
    except Exception:
        # SMTP/Resend 장애 대비 — 남은 코드 행은 TTL 만료로 무효화된다.
        raise HTTPException(
            status_code=502,
            detail="인증 메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )
    return {"sent": True}


@router.post("/auth/signup/verify", response_model=TokenResponse, status_code=201)
async def signup_verify(req: SignupVerifyRequest) -> TokenResponse:
    email = req.email.strip().lower()

    # 코드 소비 전에 username 중복을 먼저 확인 — 중복 때문에 코드가 날아가는 UX 방지
    existing = await anyio.to_thread.run_sync(partial(get_account, req.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")

    ok = await anyio.to_thread.run_sync(partial(consume_verification, email, req.code))
    if not ok:
        raise HTTPException(
            status_code=400, detail="인증 코드가 올바르지 않거나 만료되었습니다."
        )

    # bcrypt 해싱은 의도적으로 느린 CPU 연산 → 이벤트루프 비블로킹 위해 스레드에서.
    password_hash = await anyio.to_thread.run_sync(
        partial(bcrypt.hashpw, req.password.encode(), bcrypt.gensalt())
    )
    created = await anyio.to_thread.run_sync(
        partial(create_account, req.username, password_hash.decode(), email)
    )
    if not created:
        raise HTTPException(
            status_code=409, detail="이미 사용 중인 아이디 또는 이메일입니다."
        )
    return TokenResponse(access_token=create_access_token(req.username))


@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    account = await anyio.to_thread.run_sync(partial(get_account, req.username))
    # 계정 없음/비밀번호 불일치를 같은 응답으로 → 아이디 존재 탐지(enumeration) 방지
    valid = account is not None and await anyio.to_thread.run_sync(
        partial(
            bcrypt.checkpw,
            req.password.encode(),
            account["password_hash"].encode(),
        )
    )
    if not valid:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return TokenResponse(access_token=create_access_token(req.username))
