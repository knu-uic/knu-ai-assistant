"""Authentication routes shared by the React web app and Codmes."""

from functools import partial

import anyio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from api.deps import (
    create_portal_access_token,
    require_user,
    revoke_access_token,
)
from api.ratelimit import limiter
from interfaces.http.schemas.auth import (
    PortalLoginRequest,
    TokenResponse,
)
from config import RATE_LIMIT_AUTH

router = APIRouter()

@router.post("/auth/portal-login", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def portal_login(
    request: Request,
    req: PortalLoginRequest,
    background_tasks: BackgroundTasks,
) -> TokenResponse:
    """Authenticate Codmes directly with the university portal account."""
    from sync.portal_auth import (
        PortalLoginRejected,
        authenticate_portal,
        mark_portal_sync_started,
        save_portal_identity,
        sync_university_data,
    )
    from api.sessions import save_portal_session

    student_id = req.student_id.strip()
    try:
        portal_auth = await anyio.to_thread.run_sync(
            partial(authenticate_portal, student_id, req.password)
        )
    except PortalLoginRejected as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    if portal_auth is None:
        raise HTTPException(
            status_code=401,
            detail="공주대 포털 학번 또는 비밀번호를 확인해주세요.",
        )
    await anyio.to_thread.run_sync(
        partial(save_portal_identity, student_id, portal_auth.get("profile"))
    )
    await anyio.to_thread.run_sync(
        partial(save_portal_session, student_id, portal_auth["storage_state"])
    )
    mark_portal_sync_started(student_id)
    background_tasks.add_task(
        sync_university_data,
        student_id,
        portal_auth["storage_state"],
        req.password,
        portal_auth.get("profile"),
    )
    return TokenResponse(access_token=create_portal_access_token(student_id))


@router.post("/auth/logout")
@limiter.limit(RATE_LIMIT_AUTH)
async def logout(request: Request, principal: str = Depends(require_user)) -> dict:
    from api.deps import portal_student_id
    from api.sessions import delete_portal_session

    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    student_id = portal_student_id(principal)
    if student_id:
        await anyio.to_thread.run_sync(partial(delete_portal_session, student_id))
    return {
        "logged_out": True,
        "session_revoked": revoke_access_token(token, principal),
    }
