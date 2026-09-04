"""Compose the HTTP interfaces without changing their public URL contract."""

from fastapi import Depends, FastAPI

from api.deps import require_user
from interfaces.http.codmes import plugin_data
from interfaces.http.shared import assets, auth, health, me, notices
from interfaces.http.web import chat, lms, portal, search
from interfaces.http import admin


def register_http_routes(app: FastAPI) -> None:
    """Attach shared, React-only, and Codmes-only HTTP adapters.

    The grouping here is architectural ownership, not a URL namespace.
    Existing `/api/*` paths remain stable for both clients.
    """

    # Shared contracts used by both the React app and the Codmes surface.
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(notices.router, prefix="/api")
    app.include_router(assets.router, prefix="/api")
    app.include_router(me.router, prefix="/api", dependencies=[Depends(require_user)])

    # Standalone React web application contracts.
    app.include_router(chat.router, prefix="/api", dependencies=[Depends(require_user)])
    app.include_router(search.router, prefix="/api", dependencies=[Depends(require_user)])
    app.include_router(portal.router, prefix="/api", dependencies=[Depends(require_user)])
    app.include_router(lms.router, prefix="/api", dependencies=[Depends(require_user)])

    # Codmes-native Surface data adapters.
    app.include_router(plugin_data.router, prefix="/api")

    # 별도 KNU Server Manager에서만 사용하는 로컬 관리자 계약.
    app.include_router(admin.router, prefix="/api")
