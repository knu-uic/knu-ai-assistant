from functools import partial

import anyio
import bcrypt
from fastapi import APIRouter, HTTPException

from db.accounts import create_account, get_account
from api.deps import create_access_token
from api.schemas.auth import LoginRequest, SignupRequest, TokenResponse

router = APIRouter()


@router.post("/auth/signup", response_model=TokenResponse, status_code=201)
async def signup(req: SignupRequest) -> TokenResponse:
    # bcrypt 해싱은 의도적으로 느린 CPU 연산 → 이벤트루프 비블로킹 위해 스레드에서.
    password_hash = await anyio.to_thread.run_sync(
        partial(bcrypt.hashpw, req.password.encode(), bcrypt.gensalt())
    )
    created = await anyio.to_thread.run_sync(
        partial(create_account, req.username, password_hash.decode())
    )
    if not created:
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
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
