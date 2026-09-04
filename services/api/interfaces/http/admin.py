"""로컬 KNU Server Manager 전용 관리자 API."""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from api.jobs import get_arq_pool
from api.asset_files import resolve_asset_path
from api.codex_oauth import (
    cancel_login,
    discover_models,
    list_accounts as list_codex_accounts,
    poll_login,
    remove_account as remove_codex_account,
    select_account as select_codex_account,
    start_login,
)
from api.runtime_settings import (
    ALLOWED_CRAWL_INTERVAL_HOURS,
    ALLOWED_VLM_PROVIDERS,
    load_settings,
    public_settings,
    save_settings,
)
from db.pool import pool
from db.documents import CURRENT_NOTICE_EXTRACTION_VERSION, NOTICE_CATEGORIES
from interfaces.mcp.server import get_public_tool_catalog

router = APIRouter(prefix="/admin", tags=["server-manager"])


def require_admin(request: Request, authorization: str | None = Header(default=None)) -> None:
    configured = os.getenv("KNU_ADMIN_TOKEN", "").strip()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if configured:
        if supplied != configured:
            raise HTTPException(status_code=401, detail="관리자 토큰이 올바르지 않습니다.")
        return
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="관리자 토큰 없이 원격에서 접근할 수 없습니다.")


Admin = Depends(require_admin)


def _stored_file_bytes(storage_paths: list[str] | tuple[str, ...] | None) -> int:
    """Return the size of unique, locally stored notice assets."""
    total = 0
    for storage_path in dict.fromkeys(storage_paths or []):
        if not storage_path:
            continue
        try:
            path = resolve_asset_path(str(storage_path))
            if path.is_file():
                total += path.stat().st_size
        except (HTTPException, OSError):
            # A missing legacy file must not make the data catalog unavailable.
            continue
    return total


NOTICE_DATABASE_BYTES_SQL = """
    COALESCE(pg_column_size(n), 0)
    + COALESCE((SELECT sum(pg_column_size(a)) FROM notice_asset a WHERE a.notice_id=n.id), 0)
    + COALESCE((SELECT sum(pg_column_size(p)) FROM notice_period p WHERE p.notice_id=n.id), 0)
    + COALESCE((SELECT sum(pg_column_size(aud)) FROM notice_audience aud WHERE aud.notice_id=n.id), 0)
    + COALESCE((SELECT sum(pg_column_size(app)) FROM notice_application app WHERE app.notice_id=n.id), 0)
    + COALESCE((SELECT sum(pg_column_size(ch)) FROM notice_chunk ch WHERE ch.notice_id=n.id), 0)
"""

NOTICE_STORAGE_PATHS_SQL = """
    ARRAY(SELECT DISTINCT a.storage_path FROM notice_asset a
          WHERE a.notice_id=n.id AND a.storage_path IS NOT NULL)
"""


class VlmSettings(BaseModel):
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str | None = None


def _provider_base_url(provider: str, base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value:
        return value
    if provider == "ollama":
        return "http://127.0.0.1:11434/v1"
    if provider == "lmstudio":
        return "http://127.0.0.1:1234/v1"
    return value


def _server_root(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


def _unique_models(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        model = str(value or "").strip()
        if model and model not in result:
            result.append(model)
    return result


async def _discover_vlm_models(req: VlmSettings) -> dict:
    saved = load_settings()["vlm"]
    key = req.api_key or saved.get("api_key", "")
    provider = req.provider
    base = _provider_base_url(provider, req.base_url)
    if provider == "openai-codex":
        return {"ok": True, **discover_models()}

    headers = {"Authorization": f"Bearer {key or 'local'}"}
    async with httpx.AsyncClient(timeout=12) as client:
        if provider == "ollama":
            response = await client.get(f"{_server_root(base)}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            names = [
                item.get("model") or item.get("name")
                for item in models
                if isinstance(item, dict)
                and (
                    not isinstance(item.get("capabilities"), list)
                    or any(capability in {"completion", "tools", "thinking"} for capability in item["capabilities"])
                )
            ]
            return {"ok": True, "provider": provider, "base_url": base, "models": _unique_models(names)}
        if provider == "lmstudio":
            root = _server_root(base)
            native = await client.get(f"{root}/api/v1/models", headers=headers)
            if native.is_success:
                items = native.json().get("models", [])
                names = [
                    item.get("key") or item.get("id")
                    for item in items
                    if isinstance(item, dict) and str(item.get("type") or "").lower() != "embedding"
                ]
                return {"ok": True, "provider": provider, "base_url": base, "models": _unique_models(names)}
            response = await client.get(f"{base}/models", headers=headers)
            response.raise_for_status()
            names = [item.get("id") for item in response.json().get("data", []) if isinstance(item, dict)]
            return {"ok": True, "provider": provider, "base_url": base, "models": _unique_models(names)}
        if provider == "openai":
            response = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            names = [item.get("id") for item in response.json().get("data", []) if isinstance(item, dict)]
            return {"ok": True, "provider": provider, "models": _unique_models(names)}
        if provider == "google":
            response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
            response.raise_for_status()
            names = [item.get("name", "").removeprefix("models/") for item in response.json().get("models", []) if isinstance(item, dict)]
            return {"ok": True, "provider": provider, "models": _unique_models(names)}
    raise HTTPException(status_code=422, detail="지원하지 않는 VLM 제공자입니다.")


class RuntimeSettingsUpdate(BaseModel):
    crawl_enabled: bool | None = None
    crawl_interval_hours: int
    crawl_request: dict[str, Any] | None = None
    vlm: VlmSettings


CRAWL_SOURCES = (
    {"code": "main_notice", "name": "공주대학교 학생 공지", "paged": True},
    {"code": "cse_notice", "name": "컴퓨터공학과 학과공지", "paged": True},
    {"code": "business_notice", "name": "경영학과 학과공지", "paged": True},
    {"code": "cse_curriculum", "name": "컴퓨터공학과 교과과정표", "paged": False},
    {"code": "business_curriculum", "name": "경영학과 교과과정표", "paged": False},
    {"code": "scholarship_info", "name": "공주대학교 장학안내", "paged": False},
)
CRAWL_SOURCE_CODES = {source["code"] for source in CRAWL_SOURCES}


class CrawlRunRequest(BaseModel):
    mode: Literal["all", "recent", "range"] = "all"
    start_page: int = Field(default=1, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    recent_days: int = Field(default=7, ge=1, le=90)
    refresh_outdated_extraction: bool = False
    source_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.mode == "range" and self.end_page is None:
            raise ValueError("범위 크롤링은 끝 페이지가 필요합니다.")
        if self.end_page is not None and self.end_page < self.start_page:
            raise ValueError("끝 페이지는 시작 페이지보다 크거나 같아야 합니다.")
        unknown = set(self.source_codes) - CRAWL_SOURCE_CODES
        if unknown:
            raise ValueError(f"알 수 없는 크롤링 소스: {', '.join(sorted(unknown))}")
        return self


class AccountUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: str | None = Field(default=None, max_length=100)
    student_id: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=50)
    major: str | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1, le=10)


@router.get("/status", dependencies=[Admin])
async def admin_status() -> dict:
    async with pool.connection() as conn:
        counts = await (await conn.execute(
            "SELECT (SELECT count(*) FROM notice), (SELECT count(*) FROM accounts), "
            "(SELECT count(*) FROM extraction_review)"
        )).fetchone()
    return {
        "status": "ok",
        "notice_count": counts[0],
        "account_count": counts[1],
        "review_count": counts[2],
        "settings": public_settings(),
    }


@router.get("/tools", dependencies=[Admin])
async def admin_tools() -> dict:
    """Expose the exact tool catalog published by this MCP server."""
    return await get_public_tool_catalog()


@router.get("/settings", dependencies=[Admin])
async def get_settings() -> dict:
    result = public_settings()
    result["capabilities"] = {
        "crawl_intervals": list(ALLOWED_CRAWL_INTERVAL_HOURS),
        "crawl_sources": list(CRAWL_SOURCES),
        "crawl_modes": ["all", "recent", "range"],
        "current_extraction_version": CURRENT_NOTICE_EXTRACTION_VERSION,
        "vlm_providers": list(ALLOWED_VLM_PROVIDERS),
        "codex_oauth": "available",
    }
    return result


@router.put("/settings", dependencies=[Admin])
async def update_settings(req: RuntimeSettingsUpdate) -> dict:
    if req.crawl_interval_hours not in ALLOWED_CRAWL_INTERVAL_HOURS:
        raise HTTPException(status_code=422, detail="크롤링 주기는 1, 6, 12, 24시간 중 하나여야 합니다.")
    if req.vlm.provider not in ALLOWED_VLM_PROVIDERS:
        raise HTTPException(status_code=422, detail="지원하지 않는 VLM 제공자입니다.")
    previous = load_settings()
    payload = req.model_dump()
    if payload["crawl_enabled"] is None:
        payload["crawl_enabled"] = previous["crawl_enabled"]
    if payload["crawl_request"] is None:
        payload["crawl_request"] = previous["crawl_request"]
    else:
        try:
            payload["crawl_request"] = CrawlRunRequest.model_validate(payload["crawl_request"]).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if previous["crawl_enabled"] and payload["crawl_enabled"] and payload["crawl_request"] != previous["crawl_request"]:
            raise HTTPException(
                status_code=409,
                detail="자동 수집을 끈 다음 수집 설정을 변경하세요.",
            )
    if not payload["vlm"].get("api_key"):
        payload["vlm"]["api_key"] = previous["vlm"].get("api_key", "")
    return public_settings(save_settings(payload))


@router.post("/settings/test-vlm", dependencies=[Admin])
async def test_vlm(req: VlmSettings) -> dict:
    try:
        return await _discover_vlm_models(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"VLM 연결 실패: {exc}") from exc


@router.post("/settings/models", dependencies=[Admin])
async def list_vlm_models(req: VlmSettings) -> dict:
    try:
        result = await _discover_vlm_models(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"모델 목록 조회 실패: {exc}") from exc
    if not result.get("models"):
        raise HTTPException(status_code=409, detail="이 제공자에서 사용할 수 있는 모델을 찾지 못했습니다.")
    return result


@router.get("/auth/codex/accounts", dependencies=[Admin])
async def codex_accounts() -> dict:
    return {"items": list_codex_accounts()}


@router.post("/auth/codex/login", dependencies=[Admin])
async def codex_login_start() -> dict:
    try:
        return await start_login()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Codex 로그인 시작 실패: {exc}") from exc


@router.get("/auth/codex/login/{session_id}", dependencies=[Admin])
async def codex_login_status(session_id: str) -> dict:
    try:
        return await poll_login(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/auth/codex/login/{session_id}", dependencies=[Admin])
async def codex_login_cancel(session_id: str) -> dict:
    return {"canceled": cancel_login(session_id)}


@router.put("/auth/codex/accounts/{account_id}/select", dependencies=[Admin])
async def codex_account_select(account_id: str) -> dict:
    try:
        return {"account": select_codex_account(account_id)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/auth/codex/accounts/{account_id}", dependencies=[Admin])
async def codex_account_remove(account_id: str) -> dict:
    removed = remove_codex_account(account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
    return {"removed": True}


@router.get("/auth/codex/models", dependencies=[Admin])
async def codex_models() -> dict:
    try:
        return discover_models()
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Codex 모델 조회 실패: {exc}") from exc


@router.post("/crawl/run", dependencies=[Admin])
async def run_crawl(req: CrawlRunRequest | None = None) -> dict:
    request = req or CrawlRunRequest()
    if load_settings()["crawl_enabled"]:
        raise HTTPException(
            status_code=409,
            detail="자동 수집이 켜져 있을 때는 수동 수집을 시작할 수 없습니다. 자동 수집을 꺼고 시작하세요.",
        )
    redis = await get_arq_pool()
    job = await redis.enqueue_job(
        "poll_notices",
        request.model_dump(),
        _job_id="manual-notice-crawl",
    )
    if job is None:
        raise HTTPException(status_code=409, detail="이미 크롤링이 실행 중입니다.")
    return {"ok": True, "job_id": job.job_id, "request": request.model_dump()}


@router.get("/crawl/status", dependencies=[Admin])
async def crawl_status() -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE status = 'completed'),
                   count(*) FILTER (WHERE status = 'discovered'),
                   count(*) FILTER (WHERE status = 'failed'),
                   max(last_seen_at)
            FROM crawl_url_state
            """
        )).fetchone()
    redis = await get_arq_pool()
    active = bool(await redis.exists("notice-crawl:active"))
    return {
        "active": active,
        "total": row[0],
        "completed": row[1],
        "discovered": row[2],
        "failed": row[3],
        "last_seen_at": row[4],
    }


@router.get("/notices", dependencies=[Admin])
async def list_notices(
    q: str = "",
    source_code: str = "",
    category: str = "",
    year: int | None = Query(default=None, ge=1900, le=2200),
    date_from: date | None = None,
    date_to: date | None = None,
    archive: Literal["active", "archived", "all"] = "all",
    extraction_version: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="종료일은 시작일보다 빠를 수 없습니다.")
    pattern = f"%{q.strip()}%"
    filters = """
        (%s = '' OR s.code = %s)
        AND (%s = '' OR n.category = %s)
        AND (%s::integer IS NULL OR EXTRACT(YEAR FROM n.posted_at) = %s::integer)
        AND (%s::date IS NULL OR n.posted_at >= %s::date)
        AND (%s::date IS NULL OR n.posted_at < %s::date + INTERVAL '1 day')
        AND (%s = '' OR n.extraction_version = %s)
        AND (
            %s = 'all'
            OR (%s = 'active' AND n.archived_at IS NULL)
            OR (%s = 'archived' AND n.archived_at IS NOT NULL)
        )
    """
    params = (
        source_code, source_code,
        category, category,
        year, year,
        date_from, date_from,
        date_to, date_to,
        extraction_version, extraction_version,
        archive, archive, archive,
    )
    async with pool.connection() as conn:
        total = (await (await conn.execute(
            f"""SELECT count(*) FROM notice n JOIN source s ON s.id=n.source_id
                WHERE (%s = '%%' OR n.title ILIKE %s OR n.content ILIKE %s)
                AND {filters}""",
            (pattern, pattern, pattern, *params),
        )).fetchone())[0]
        rows = await (await conn.execute(
            f"""SELECT n.id, n.title, n.category, n.posted_at, n.crawled_at,
                      n.extraction_confidence, n.archived_at, s.name, n.url,
                      n.extraction_version,
                      {NOTICE_DATABASE_BYTES_SQL} AS database_bytes,
                      {NOTICE_STORAGE_PATHS_SQL} AS storage_paths
               FROM notice n JOIN source s ON s.id=n.source_id
               WHERE (%s = '%%' OR n.title ILIKE %s OR n.content ILIKE %s)
               AND {filters}
               ORDER BY n.posted_at DESC NULLS LAST, n.id DESC LIMIT %s OFFSET %s""",
            (pattern, pattern, pattern, *params, limit, offset),
        )).fetchall()
    items = []
    keys = (
        "id", "title", "category", "posted_at", "crawled_at",
        "extraction_confidence", "archived_at", "source", "url",
        "extraction_version", "database_bytes", "storage_paths",
    )
    for row in rows:
        item = dict(zip(keys, row))
        file_bytes = _stored_file_bytes(item.pop("storage_paths", []))
        item["asset_file_bytes"] = file_bytes
        item["storage_bytes"] = int(item["database_bytes"] or 0) + file_bytes
        items.append(item)
    return {"total": total, "items": items}


@router.get("/notices/storage", dependencies=[Admin])
async def notice_storage() -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT
                   (SELECT count(*) FROM notice),
                   (SELECT COALESCE(sum(pg_column_size(n)), 0) FROM notice n)
                   + (SELECT COALESCE(sum(pg_column_size(a)), 0) FROM notice_asset a)
                   + (SELECT COALESCE(sum(pg_column_size(p)), 0) FROM notice_period p)
                   + (SELECT COALESCE(sum(pg_column_size(aud)), 0) FROM notice_audience aud)
                   + (SELECT COALESCE(sum(pg_column_size(app)), 0) FROM notice_application app)
                   + (SELECT COALESCE(sum(pg_column_size(ch)), 0) FROM notice_chunk ch)"""
        )).fetchone()
        asset_row = await (await conn.execute(
            """SELECT count(*), array_agg(DISTINCT storage_path)
               FROM notice_asset WHERE storage_path IS NOT NULL"""
        )).fetchone()
    database_bytes = int(row[1] or 0)
    asset_file_bytes = _stored_file_bytes(asset_row[1] or [])
    return {
        "bytes": database_bytes + asset_file_bytes,
        "database_bytes": database_bytes,
        "asset_file_bytes": asset_file_bytes,
        "notice_count": int(row[0] or 0),
        "asset_count": int(asset_row[0] or 0),
    }


@router.get("/notices/filters", dependencies=[Admin])
async def notice_filters() -> dict:
    async with pool.connection() as conn:
        sources = await (await conn.execute(
            """SELECT DISTINCT s.code, s.name
               FROM source s JOIN notice n ON n.source_id=s.id
               ORDER BY s.name"""
        )).fetchall()
        years = await (await conn.execute(
            """SELECT DISTINCT EXTRACT(YEAR FROM posted_at)::int
               FROM notice WHERE posted_at IS NOT NULL ORDER BY 1 DESC"""
        )).fetchall()
        versions = await (await conn.execute(
            """SELECT DISTINCT extraction_version FROM notice
               WHERE extraction_version IS NOT NULL ORDER BY 1 DESC"""
        )).fetchall()
    return {
        "sources": [{"code": row[0], "name": row[1]} for row in sources],
        "categories": list(NOTICE_CATEGORIES),
        "years": [row[0] for row in years],
        "extraction_versions": [row[0] for row in versions],
    }


@router.get("/notices/{notice_id}", dependencies=[Admin])
async def notice_detail(notice_id: int) -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT n.id,n.title,n.url,n.content,n.body_content,n.summary,n.category,n.topics,
                      n.posted_at,n.crawled_at,n.updated_at,n.extraction_version,
                      n.extraction_confidence,n.extra,n.archived_at,s.name,
                      """ + NOTICE_DATABASE_BYTES_SQL + """ AS database_bytes,
                      """ + NOTICE_STORAGE_PATHS_SQL + """ AS storage_paths
               FROM notice n JOIN source s ON s.id=n.source_id WHERE n.id=%s""", (notice_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
        assets = await (await conn.execute(
            "SELECT id,kind,filename,source_url,storage_path,mime_type,extracted_text,extra FROM notice_asset WHERE notice_id=%s ORDER BY order_idx,id",
            (notice_id,),
        )).fetchall()
        periods = await (await conn.execute(
            "SELECT kind,starts_on,ends_on,source_text,confidence FROM notice_period WHERE notice_id=%s ORDER BY order_idx,id",
            (notice_id,),
        )).fetchall()
        audiences = await (await conn.execute(
            "SELECT kind,value,source_text,confidence FROM notice_audience WHERE notice_id=%s ORDER BY order_idx,id",
            (notice_id,),
        )).fetchall()
    keys = ("id","title","url","content","body_content","summary","category","topics","posted_at","crawled_at","updated_at","extraction_version","extraction_confidence","extra","archived_at","source","database_bytes","storage_paths")
    result = dict(zip(keys, row))
    file_bytes = _stored_file_bytes(result.pop("storage_paths", []))
    result["asset_file_bytes"] = file_bytes
    result["storage_bytes"] = int(result["database_bytes"] or 0) + file_bytes
    result["assets"] = [dict(zip(("id","kind","filename","source_url","storage_path","mime_type","extracted_text","extra"), item)) for item in assets]
    result["periods"] = [dict(zip(("kind","starts_on","ends_on","source_text","confidence"), item)) for item in periods]
    result["audiences"] = [dict(zip(("kind","value","source_text","confidence"), item)) for item in audiences]
    return result


@router.get("/assets/{asset_id}/content", dependencies=[Admin])
async def asset_content(asset_id: int) -> FileResponse:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT storage_path,mime_type,filename FROM notice_asset WHERE id=%s", (asset_id,)
        )).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="저장된 자산 파일을 찾을 수 없습니다.")
    mime_type = str(row[1] or "")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="미리보기를 지원하는 이미지 자산이 아닙니다.")
    path = resolve_asset_path(str(row[0]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="자산 파일이 디스크에 없습니다.")
    return FileResponse(path, media_type=mime_type, filename=str(row[2] or path.name))


@router.get("/accounts", dependencies=[Admin])
async def list_accounts() -> dict:
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """SELECT a.id,a.username,a.email,a.student_id,a.created_at,u.name,u.major,u.year
               FROM accounts a LEFT JOIN users u ON u.student_id=a.student_id ORDER BY a.created_at DESC"""
        )).fetchall()
    keys = ("id","username","email","student_id","created_at","name","major","year")
    return {"items": [dict(zip(keys, row)) for row in rows]}


@router.put("/accounts/{account_id}", dependencies=[Admin])
async def update_account(account_id: int, req: AccountUpdate) -> dict:
    async with pool.connection() as conn:
        current = await (await conn.execute("SELECT student_id FROM accounts WHERE id=%s", (account_id,))).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        try:
            await conn.execute(
                "UPDATE accounts SET username=%s,email=%s,student_id=%s WHERE id=%s",
                (req.username, req.email or None, req.student_id or None, account_id),
            )
            if req.student_id:
                await conn.execute(
                    """INSERT INTO users(student_id,name,major,year) VALUES(%s,%s,%s,%s)
                       ON CONFLICT(student_id) DO UPDATE SET name=EXCLUDED.name,major=EXCLUDED.major,year=EXCLUDED.year""",
                    (req.student_id, req.name, req.major, req.year),
                )
            await conn.commit()
        except Exception as exc:
            await conn.rollback()
            raise HTTPException(status_code=409, detail=f"계정 수정 실패: {exc}") from exc
    return {"ok": True}


@router.delete("/accounts/{account_id}", dependencies=[Admin])
async def delete_account(account_id: int, delete_linked_data: bool = False) -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT student_id FROM accounts WHERE id=%s", (account_id,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        student_id = row[0]
        await conn.execute("DELETE FROM accounts WHERE id=%s", (account_id,))
        if delete_linked_data and student_id:
            remaining = await (await conn.execute("SELECT 1 FROM accounts WHERE student_id=%s LIMIT 1", (student_id,))).fetchone()
            if not remaining:
                await conn.execute("DELETE FROM users WHERE student_id=%s", (student_id,))
        await conn.commit()
    return {"ok": True, "linked_data_deleted": bool(delete_linked_data and student_id)}
