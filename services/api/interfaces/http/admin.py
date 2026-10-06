"""로컬 KNU Server Manager 전용 관리자 API."""
from __future__ import annotations

import base64
import asyncio
import json
import os
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
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
    ALLOWED_EMBEDDING_PROVIDERS,
    ALLOWED_RERANKER_PROVIDERS,
    ALLOWED_REFINE_PROVIDERS,
    ALLOWED_SCHOOL_CHAT_PROVIDERS,
    ALLOWED_VLM_PROVIDERS,
    DEFAULT_RERANKER_MODEL,
    load_settings,
    public_settings,
    save_settings,
)
from embedding.datasets import activate_dataset, delete_dataset, get_dataset, list_datasets
from embedding.rebuild import (
    rebuild_status,
    recover_interrupted_builds,
    resume_dataset,
    start_rebuild,
)
from model import get_embeddings
from retrieval.rerank import rerank_scores
from retrieval.reranker_runtime import (
    SUPPORTED_MODELS,
    delete_reranker_model,
    reranker_status,
    start_reranker_download,
)
from db.pool import pool
from db.crawl_progress import load_crawl_progress, save_crawl_progress
from db.documents import CURRENT_NOTICE_EXTRACTION_VERSION, NOTICE_CATEGORIES
from interfaces.mcp.server import get_public_tool_catalog
from pipelines.list_sync import sync_notice_lists
from workers.crawl_control import (
    NOTICE_CRAWL_ACTIVE_KEY,
    NOTICE_CRAWL_PAUSE_KEY,
    NOTICE_CRAWL_PENDING_KEY,
    NOTICE_CRAWL_PROGRESS_KEY,
    NOTICE_CRAWL_STOP_KEY,
    MANUAL_NOTICE_JOB_PREFIX,
)

router = APIRouter(prefix="/admin", tags=["server-manager"])


DATABASE_TABLE_METADATA: dict[str, tuple[str, str, str]] = {
    "source": ("수집 소스", "content", "공지·대학생활 원문의 출처와 종류를 관리합니다."),
    "content": ("통합 콘텐츠", "content", "공지와 대학생활 문서의 공통 제목·본문·출처를 저장합니다."),
    "notice": ("공지", "content", "통합 콘텐츠 중 공지인 항목의 하위 엔터티입니다."),
    "academic_document": ("대학생활 문서", "content", "통합 콘텐츠 중 상시 학사정보인 항목의 하위 엔터티입니다."),
    "category": ("카테고리", "content", "장학·수강·취업 등 정규화된 분류 사전입니다."),
    "topic": ("토픽", "content", "콘텐츠에서 추출된 세부 주제 사전입니다."),
    "content_topic": ("콘텐츠 토픽", "content", "콘텐츠와 세부 주제의 다대다 관계입니다."),
    "notice_period": ("일정", "content", "접수·행사 등 콘텐츠에서 추출한 기간입니다."),
    "notice_target": ("대상", "content", "학과·학년 등 콘텐츠의 대상 조건입니다."),
    "notice_application": ("신청 정보", "content", "신청 방법·링크·서류·문의처를 저장합니다."),
    "content_asset": ("첨부 자산", "search", "첨부파일과 추출 텍스트를 저장합니다."),
    "content_chunk": ("검색 청크", "search", "본문·첨부 검색 단위와 임베딩을 저장합니다."),
    "embedding_dataset": ("임베딩 데이터셋", "search", "모델별 벡터 데이터셋과 생성 상태를 관리합니다."),
    "extraction_review": ("추출 검토", "operation", "신뢰도가 낮은 자동 추출 결과의 검토 상태입니다."),
    "crawl_url_state": ("수집 URL 상태", "operation", "URL별 발견·처리·실패 상태를 기록합니다."),
    "crawl_run_state": ("수집 실행 상태", "operation", "중단 후 재개할 수집 실행 체크포인트입니다."),
    "users": ("사용자 계정", "account", "학교 포털 인증으로 생성된 사용자와 학적 정보입니다."),
    "student_llm_account": ("학생 개인 LLM 계정", "account", "학생별 암호화된 대화 모델 자격증명입니다."),
}


def _database_table_metadata(table_name: str) -> tuple[str, str, str]:
    return DATABASE_TABLE_METADATA.get(
        table_name,
        (table_name, "other", "서버가 사용하는 보조 테이블입니다."),
    )


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
    + COALESCE((SELECT sum(pg_column_size(a)) FROM content_asset a WHERE a.content_id=n.content_id), 0)
    + COALESCE((SELECT sum(pg_column_size(p)) FROM notice_period p WHERE p.notice_id=n.content_id), 0)
    + COALESCE((SELECT sum(pg_column_size(aud)) FROM notice_target aud WHERE aud.notice_id=n.content_id), 0)
    + COALESCE((SELECT sum(pg_column_size(app)) FROM notice_application app WHERE app.notice_id=n.content_id), 0)
    + COALESCE((SELECT sum(pg_column_size(ch)) FROM content_chunk ch WHERE ch.content_id=n.content_id), 0)
"""

NOTICE_STORAGE_PATHS_SQL = """
    ARRAY(SELECT DISTINCT a.storage_path FROM content_asset a
          WHERE a.content_id=n.content_id AND a.storage_path IS NOT NULL)
"""

NOTICE_EMBEDDING_MODELS_SQL = """
    ARRAY(
        SELECT DISTINCT nc2.embedding_provider || ' · ' || nc2.embedding_model
               || ' · ' || nc2.embedding_dimension || '차원'
        FROM content_chunk nc2
        WHERE nc2.content_id=n.content_id
        ORDER BY 1
    )
"""


class VlmSettings(BaseModel):
    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str | None = None
    purpose: Literal["vlm", "refine", "school_chat"] = "vlm"


class SchoolChatSettings(BaseModel):
    enabled: bool = False
    provider: Literal["ollama", "lmstudio", "openai", "google"] = "ollama"
    model: str = ""
    base_url: str = "http://127.0.0.1:11434/v1"
    api_key: str | None = None


def _validate_school_chat(value: SchoolChatSettings) -> None:
    if value.provider in {"ollama", "lmstudio"}:
        parsed = urlsplit(value.base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.path.rstrip("/") not in {"", "/v1"} or parsed.query or parsed.fragment):
            raise HTTPException(422, "로컬 학교 대화 모델은 서버 자신의 Ollama/LM Studio 주소만 사용할 수 있습니다.")
    if value.enabled and not value.model.strip():
        raise HTTPException(422, "학교 대화 모델을 켜려면 모델을 선택하세요.")


class ImportApiKeyRequest(BaseModel):
    purpose: Literal["vlm", "refine", "school_chat"]
    provider: Literal["openai", "google"]
    model: str
    base_url: str = ""


def _environment_api_key(provider: str) -> str:
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY") or ""
    if provider == "google":
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    return ""


class EmbeddingSettings(BaseModel):
    provider: str = "ollama"
    model: str = ""
    base_url: str = ""
    dimension: int | None = Field(default=None, ge=1, le=4096)
    chunk_size: int = Field(default=280, ge=64, le=4000)
    chunk_overlap: int = Field(default=80, ge=0, le=3999)
    api_key: str | None = None

    @model_validator(mode="after")
    def validate_chunking(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("청크 중첩은 청크 크기보다 작아야 합니다.")
        return self


class EmbeddingDatasetAction(BaseModel):
    api_key: str | None = None


class RerankerSettings(BaseModel):
    enabled: bool = True
    provider: Literal["local"] = "local"
    model: str = DEFAULT_RERANKER_MODEL
    max_length: int = Field(default=512, ge=128, le=2048)

    @model_validator(mode="after")
    def validate_model(self):
        if self.model not in SUPPORTED_MODELS:
            raise ValueError("지원하지 않는 로컬 리랭커 모델입니다.")
        return self


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
    saved = load_settings()[req.purpose]
    saved_key = saved.get("api_key", "") if saved.get("provider") == req.provider else ""
    key = req.api_key or saved_key or _environment_api_key(req.provider)
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
            async def chat_model_name(item: dict) -> str | None:
                name = str(item.get("model") or item.get("name") or "").strip()
                if not name:
                    return None
                capabilities = item.get("capabilities")
                if not isinstance(capabilities, list):
                    try:
                        detail = await client.post(f"{_server_root(base)}/api/show", json={"model": name})
                        detail.raise_for_status()
                        capabilities = detail.json().get("capabilities")
                    except (httpx.HTTPError, ValueError):
                        return None
                required = {"completion", "tools"} if req.purpose == "school_chat" else {"completion"}
                return name if isinstance(capabilities, list) and required.issubset(capabilities) else None

            names = await asyncio.gather(*(chat_model_name(item) for item in models if isinstance(item, dict)))
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
            names = [item.get("id") for item in response.json().get("data", [])
                     if isinstance(item, dict) and (
                         req.purpose != "school_chat" or
                         str(item.get("id") or "").startswith("gpt-") or
                         (str(item.get("id") or "").startswith("o")
                          and str(item.get("id") or "")[1:2].isdigit())
                     )]
            return {"ok": True, "provider": provider, "models": _unique_models(names)}
        if provider == "google":
            response = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
            response.raise_for_status()
            names = [item.get("name", "").removeprefix("models/") for item in response.json().get("models", [])
                     if isinstance(item, dict)
                     and str(item.get("name") or "").startswith("models/gemini-")
                     and "generateContent" in (item.get("supportedGenerationMethods") or [])]
            return {"ok": True, "provider": provider, "models": _unique_models(names)}
    raise HTTPException(status_code=422, detail="지원하지 않는 VLM 제공자입니다.")


async def _discover_embedding_models(req: EmbeddingSettings) -> dict:
    saved = load_settings()["embedding"]
    key = req.api_key or saved.get("api_key", "")
    provider = req.provider
    base = _provider_base_url(provider, req.base_url)
    headers = {"Authorization": f"Bearer {key or 'local'}"}
    async with httpx.AsyncClient(timeout=12) as client:
        if provider == "ollama":
            response = await client.get(f"{_server_root(base)}/api/tags")
            response.raise_for_status()
            names = [
                item.get("model") or item.get("name")
                for item in response.json().get("models", [])
                if isinstance(item, dict)
                and "embedding" in (item.get("capabilities") or [])
            ]
        elif provider == "lmstudio":
            root = _server_root(base)
            native = await client.get(f"{root}/api/v1/models", headers=headers)
            if native.is_success:
                names = [
                    item.get("key") or item.get("id")
                    for item in native.json().get("models", [])
                    if isinstance(item, dict)
                    and str(item.get("type") or "").lower() == "embedding"
                ]
            else:
                response = await client.get(f"{base}/models", headers=headers)
                response.raise_for_status()
                names = [
                    item.get("id") for item in response.json().get("data", [])
                    if isinstance(item, dict)
                ]
        elif provider == "openai":
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            response.raise_for_status()
            names = [
                item.get("id") for item in response.json().get("data", [])
                if isinstance(item, dict) and "embedding" in str(item.get("id") or "")
            ]
        elif provider == "google":
            response = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": key},
            )
            response.raise_for_status()
            names = [
                item.get("name", "").removeprefix("models/")
                for item in response.json().get("models", [])
                if isinstance(item, dict)
                and "embedContent" in (item.get("supportedGenerationMethods") or [])
            ]
        else:
            raise HTTPException(status_code=422, detail="지원하지 않는 임베딩 제공자입니다.")
    return {"ok": True, "provider": provider, "base_url": base, "models": _unique_models(names)}


async def _discover_embedding_model_info(req: EmbeddingSettings) -> dict:
    provider = req.provider
    base = _provider_base_url(provider, req.base_url)
    if provider != "ollama":
        return {
            "ok": True, "provider": provider, "model": req.model,
            "base_url": base, "native_dimension": None,
        }
    if not req.model.strip():
        raise HTTPException(status_code=422, detail="임베딩 모델을 선택하세요.")
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{_server_root(base)}/api/show", json={"model": req.model}
        )
        response.raise_for_status()
    payload = response.json()
    dimensions = [
        int(value)
        for key, value in (payload.get("model_info") or {}).items()
        if str(key).endswith(".embedding_length")
        and isinstance(value, (int, float))
        and int(value) > 0
    ]
    if not dimensions:
        raise HTTPException(
            status_code=409,
            detail="Ollama 모델 메타데이터에서 embedding length를 확인하지 못했습니다.",
        )
    return {
        "ok": True, "provider": provider, "model": req.model,
        "base_url": base, "native_dimension": max(dimensions),
        "parameter_size": (payload.get("details") or {}).get("parameter_size"),
    }


class RuntimeSettingsUpdate(BaseModel):
    crawl_enabled: bool | None = None
    crawl_interval_hours: int
    crawl_request: dict[str, Any] | None = None
    vlm: VlmSettings
    refine: VlmSettings | None = None
    school_chat: SchoolChatSettings | None = None
    embedding: EmbeddingSettings | None = None
    reranker: RerankerSettings | None = None


CRAWL_SOURCES = (
    {"code": "main_notice", "name": "공주대학교 학생 공지", "paged": True},
    {"code": "cse_notice", "name": "컴퓨터공학과 학과공지", "paged": True},
    {"code": "software_notice", "name": "소프트웨어공학과 학과공지", "paged": True},
    {"code": "business_notice", "name": "경영학과 학과공지", "paged": True},
    {"code": "cse_curriculum", "name": "컴퓨터공학과 교과과정표", "paged": False},
    {"code": "software_curriculum", "name": "소프트웨어공학과 교과과정표", "paged": False},
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


class UserAccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    major: str | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1, le=10)


@router.get("/status", dependencies=[Admin])
async def admin_status() -> dict:
    async with pool.connection() as conn:
        counts = await (await conn.execute(
            "SELECT (SELECT count(*) FROM content), (SELECT count(*) FROM users), "
            "(SELECT count(*) FROM extraction_review)"
        )).fetchone()
    return {
        "status": "ok",
        "notice_count": counts[0],
        "account_count": counts[1],
        "review_count": counts[2],
        "settings": public_settings(),
    }


@router.get("/database/schema", dependencies=[Admin])
async def database_schema() -> dict:
    """Return the physical PostgreSQL model used by the running server.

    The manager intentionally reads PostgreSQL's catalog instead of keeping a
    second, hand-written schema description that can drift from migrations.
    """
    async with pool.connection() as conn:
        column_rows = await (await conn.execute(
            """
            SELECT c.table_name, c.column_name, c.data_type, c.udt_name,
                   c.is_nullable, c.column_default, c.ordinal_position
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema
             AND t.table_name = c.table_name
            WHERE c.table_schema = 'public'
              AND t.table_type = 'BASE TABLE'
              AND c.table_name <> 'schema_migrations'
            ORDER BY c.table_name, c.ordinal_position
            """
        )).fetchall()
        key_rows = await (await conn.execute(
            """
            SELECT tc.table_name, kcu.column_name, tc.constraint_type,
                   ccu.table_name AS referenced_table,
                   ccu.column_name AS referenced_column,
                   rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            LEFT JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            LEFT JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
             AND tc.constraint_schema = rc.constraint_schema
            WHERE tc.table_schema = 'public'
              AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
            ORDER BY tc.table_name, tc.constraint_type DESC, kcu.ordinal_position
            """
        )).fetchall()
        count_rows = await (await conn.execute(
            """
            SELECT relname, n_live_tup::bigint
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            """
        )).fetchall()
        migration_rows = await (await conn.execute(
            """
            SELECT version, applied_at
            FROM schema_migrations
            ORDER BY version
            """
        )).fetchall()

    counts = {str(row[0]): int(row[1] or 0) for row in count_rows}
    keys: dict[tuple[str, str], dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    for table, column, kind, referenced_table, referenced_column, delete_rule in key_rows:
        key = {
            "kind": "pk" if kind == "PRIMARY KEY" else "fk",
            "references": (
                f"{referenced_table}.{referenced_column}"
                if referenced_table and referenced_column else None
            ),
        }
        keys[(str(table), str(column))] = key
        if kind == "FOREIGN KEY":
            relationships.append({
                "from_table": table,
                "from_column": column,
                "to_table": referenced_table,
                "to_column": referenced_column,
                "delete_rule": delete_rule,
            })

    tables: dict[str, dict[str, Any]] = {}
    for table, column, data_type, udt_name, nullable, default, _position in column_rows:
        table = str(table)
        label, group, description = _database_table_metadata(table)
        item = tables.setdefault(table, {
            "name": table,
            "label": label,
            "group": group,
            "description": description,
            "row_count": counts.get(table, 0),
            "columns": [],
        })
        key = keys.get((table, str(column)), {})
        item["columns"].append({
            "name": column,
            "type": udt_name if data_type == "USER-DEFINED" else data_type,
            "nullable": nullable == "YES",
            "default": default,
            **key,
        })

    migrations = [
        {"version": row[0], "applied_at": row[1]}
        for row in migration_rows
    ]
    return {
        "model": "content-v3",
        "storage_rule": "공통 필드는 content에 저장하고 notice와 academic_document 하위 엔터티로 구분",
        "tables": list(tables.values()),
        "relationships": relationships,
        "migrations": migrations,
        "latest_migration": migrations[-1]["version"] if migrations else None,
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
        "refine_providers": list(ALLOWED_REFINE_PROVIDERS),
        "school_chat_providers": list(ALLOWED_SCHOOL_CHAT_PROVIDERS),
        "embedding_providers": list(ALLOWED_EMBEDDING_PROVIDERS),
        "reranker_providers": list(ALLOWED_RERANKER_PROVIDERS),
        "reranker_models": list(SUPPORTED_MODELS),
        "codex_oauth": "available",
    }
    return result


@router.put("/settings", dependencies=[Admin])
async def update_settings(req: RuntimeSettingsUpdate) -> dict:
    if req.crawl_interval_hours not in ALLOWED_CRAWL_INTERVAL_HOURS:
        raise HTTPException(status_code=422, detail="크롤링 주기는 1, 6, 12, 24시간 중 하나여야 합니다.")
    if req.vlm.provider not in ALLOWED_VLM_PROVIDERS:
        raise HTTPException(status_code=422, detail="지원하지 않는 VLM 제공자입니다.")
    if req.refine is not None and req.refine.provider not in ALLOWED_REFINE_PROVIDERS:
        raise HTTPException(status_code=422, detail="지원하지 않는 공지 정제 제공자입니다.")
    if req.school_chat is not None:
        _validate_school_chat(req.school_chat)
    previous = load_settings()
    if req.crawl_enabled and rebuild_status()["state"] == "running":
        raise HTTPException(
            status_code=409,
            detail="임베딩 모델 교체가 끝난 뒤 자동 수집을 켜세요.",
        )
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
        payload["vlm"]["api_key"] = (
            previous["vlm"].get("api_key", "")
            if payload["vlm"]["provider"] == previous["vlm"]["provider"] else ""
        )
    if payload["refine"] is None:
        payload["refine"] = previous["refine"]
    elif not payload["refine"].get("api_key"):
        payload["refine"]["api_key"] = (
            previous["refine"].get("api_key", "")
            if payload["refine"]["provider"] == previous["refine"]["provider"] else ""
        )
    if payload["school_chat"] is None:
        payload["school_chat"] = previous["school_chat"]
    elif not payload["school_chat"].get("api_key"):
        payload["school_chat"]["api_key"] = (
            previous["school_chat"].get("api_key", "")
            if payload["school_chat"]["provider"] == previous["school_chat"]["provider"] else ""
        )
    if (payload["school_chat"]["enabled"]
            and payload["school_chat"]["provider"] in {"openai", "google"}
            and not payload["school_chat"].get("api_key")):
        raise HTTPException(422, "학교 제공 API 모델에는 학교 API 키가 필요합니다.")
    # Embedding activation is only performed by the blue-green rebuild endpoint.
    # A normal crawl/VLM settings save must never switch query vectors early.
    payload["embedding"] = previous["embedding"]
    if payload["reranker"] is None:
        payload["reranker"] = previous["reranker"]
    return public_settings(save_settings(payload))


@router.post("/settings/import-api-key", dependencies=[Admin])
async def import_api_key(req: ImportApiKeyRequest) -> dict:
    """Import a server environment key without sending it to the browser."""
    key = _environment_api_key(req.provider)
    if not key:
        raise HTTPException(status_code=404, detail="서버 환경변수에서 해당 API 키를 찾지 못했습니다.")
    current = load_settings()
    current[req.purpose] = {
        **current[req.purpose],
        "provider": req.provider,
        "model": req.model,
        "base_url": req.base_url,
        "api_key": key,
    }
    return public_settings(save_settings(current))


@router.get("/settings/reranker", dependencies=[Admin])
async def get_reranker_settings() -> dict:
    return reranker_status()


@router.put("/settings/reranker", dependencies=[Admin])
async def update_reranker_settings(req: RerankerSettings) -> dict:
    previous = load_settings()
    previous["reranker"] = req.model_dump()
    save_settings(previous)
    return reranker_status()


@router.post("/settings/reranker/download", dependencies=[Admin])
async def download_reranker_model(req: RerankerSettings) -> dict:
    return start_reranker_download(req.model)


@router.delete("/settings/reranker/model", dependencies=[Admin])
async def remove_reranker_model() -> dict:
    model = load_settings()["reranker"]["model"]
    try:
        return delete_reranker_model(model)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/settings/reranker/test", dependencies=[Admin])
async def test_reranker(req: RerankerSettings) -> dict:
    previous = load_settings()
    previous["reranker"] = req.model_dump()
    save_settings(previous)
    status = reranker_status()
    if not req.enabled:
        raise HTTPException(status_code=409, detail="리랭커를 먼저 활성화하세요.")
    if not status["installed"]:
        raise HTTPException(status_code=409, detail="리랭커 모델을 먼저 다운로드하세요.")
    try:
        scores = await anyio.to_thread.run_sync(
            rerank_scores,
            "수강신청 기간은 언제인가요?",
            ["수강신청 기간은 9월 1일부터 3일까지입니다.", "교내 주차 안내입니다."],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"리랭커 실행 실패: {exc}") from exc
    return {**reranker_status(), "ok": True, "scores": scores}


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


@router.post("/settings/embedding-models", dependencies=[Admin])
async def list_embedding_models(req: EmbeddingSettings) -> dict:
    try:
        return await _discover_embedding_models(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"임베딩 모델 목록 조회 실패: {exc}") from exc


@router.post("/settings/embedding-model-info", dependencies=[Admin])
async def embedding_model_info(req: EmbeddingSettings) -> dict:
    try:
        return await _discover_embedding_model_info(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"임베딩 모델 정보 조회 실패: {exc}") from exc


async def _checked_embedding(req: EmbeddingSettings) -> dict:
    if req.provider not in ALLOWED_EMBEDDING_PROVIDERS:
        raise HTTPException(status_code=422, detail="지원하지 않는 임베딩 제공자입니다.")
    if not req.model.strip():
        raise HTTPException(status_code=422, detail="임베딩 모델을 선택하세요.")
    saved = load_settings()["embedding"]
    target = req.model_dump()
    target["base_url"] = _provider_base_url(req.provider, req.base_url)
    target["api_key"] = req.api_key or (
        saved.get("api_key", "") if saved.get("provider") == req.provider else ""
    )
    vector = await anyio.to_thread.run_sync(
        lambda: get_embeddings(target).embed_query("KNU embedding connection test")
    )
    target["dimension"] = len(vector)
    return target


@router.post("/settings/test-embedding", dependencies=[Admin])
async def test_embedding(req: EmbeddingSettings) -> dict:
    try:
        target = await _checked_embedding(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"임베딩 연결 실패: {exc}") from exc
    return {
        "ok": True,
        "provider": target["provider"],
        "model": target["model"],
        "base_url": target["base_url"],
        "dimension": target["dimension"],
    }


@router.post("/settings/rebuild-embedding", dependencies=[Admin])
async def rebuild_embedding(req: EmbeddingSettings) -> dict:
    if load_settings()["crawl_enabled"]:
        raise HTTPException(
            status_code=409,
            detail="자동 수집을 끈 뒤 임베딩 모델을 교체하세요.",
        )
    redis = await get_arq_pool()
    if await redis.exists("notice-crawl:active"):
        raise HTTPException(
            status_code=409,
            detail="현재 공지 수집이 끝난 뒤 임베딩 모델을 교체하세요.",
        )
    try:
        target = await _checked_embedding(req)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail=f"임베딩 연결 실패: {exc}") from exc
    try:
        return start_rebuild(target)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/settings/rebuild-embedding", dependencies=[Admin])
async def get_rebuild_embedding() -> dict:
    return rebuild_status()


@router.get("/settings/embedding-datasets", dependencies=[Admin])
async def embedding_datasets() -> dict:
    await anyio.to_thread.run_sync(recover_interrupted_builds)
    return {"items": await anyio.to_thread.run_sync(list_datasets)}


async def _ensure_no_crawl() -> None:
    if load_settings()["crawl_enabled"]:
        raise HTTPException(status_code=409, detail="자동 수집을 먼저 끄세요.")
    redis = await get_arq_pool()
    if await redis.exists("notice-crawl:active"):
        raise HTTPException(status_code=409, detail="현재 공지 수집이 끝난 뒤 진행하세요.")


@router.put("/settings/embedding-datasets/{dataset_id}/activate", dependencies=[Admin])
async def activate_embedding_dataset(
    dataset_id: int, action: EmbeddingDatasetAction,
) -> dict:
    await _ensure_no_crawl()
    if rebuild_status()["state"] == "running":
        raise HTTPException(status_code=409, detail="데이터셋 생성이 끝난 뒤 전환하세요.")
    try:
        dataset = await anyio.to_thread.run_sync(
            lambda: activate_dataset(dataset_id, api_key=action.api_key or "")
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "dataset": dataset}


@router.post("/settings/embedding-datasets/{dataset_id}/sync", dependencies=[Admin])
async def sync_embedding_dataset(
    dataset_id: int, action: EmbeddingDatasetAction,
) -> dict:
    await _ensure_no_crawl()
    if not await anyio.to_thread.run_sync(lambda: get_dataset(dataset_id)):
        raise HTTPException(status_code=404, detail="임베딩 데이터셋을 찾을 수 없습니다.")
    try:
        return await anyio.to_thread.run_sync(
            lambda: resume_dataset(dataset_id, api_key=action.api_key or "")
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/settings/embedding-datasets/{dataset_id}", dependencies=[Admin])
async def remove_embedding_dataset(dataset_id: int) -> dict:
    try:
        deleted_chunks = await anyio.to_thread.run_sync(
            lambda: delete_dataset(dataset_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "deleted_chunks": deleted_chunks}


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


async def _enqueue_manual_crawl(request: CrawlRunRequest, *, resume: bool = False) -> dict:
    if rebuild_status()["state"] == "running":
        raise HTTPException(
            status_code=409,
            detail="임베딩 모델 교체가 끝난 뒤 공지 수집을 시작하세요.",
        )
    if load_settings()["crawl_enabled"]:
        raise HTTPException(
            status_code=409,
            detail="자동 수집이 켜져 있을 때는 수동 수집을 시작할 수 없습니다. 자동 수집을 꺼고 시작하세요.",
        )
    redis = await get_arq_pool()
    if await redis.exists(NOTICE_CRAWL_ACTIVE_KEY):
        raise HTTPException(status_code=409, detail="이미 크롤링이 실행 중입니다.")
    job_id = f"{MANUAL_NOTICE_JOB_PREFIX}-{uuid4().hex}"
    reserved = await redis.set(NOTICE_CRAWL_PENDING_KEY, job_id, ex=300, nx=True)
    if not reserved:
        raise HTTPException(status_code=409, detail="이미 크롤링 시작을 준비하고 있습니다.")
    if resume:
        job = await redis.enqueue_job(
            "poll_notices",
            request.model_dump(),
            True,
            _job_id=job_id,
        )
    else:
        job = await redis.enqueue_job(
            "poll_notices",
            request.model_dump(),
            _job_id=job_id,
        )
    if job is None:
        await redis.delete(NOTICE_CRAWL_PENDING_KEY)
        raise HTTPException(status_code=409, detail="이미 크롤링이 실행 중입니다.")
    return {"ok": True, "job_id": job.job_id, "request": request.model_dump()}


@router.post("/crawl/run", dependencies=[Admin])
async def run_crawl(req: CrawlRunRequest | None = None) -> dict:
    return await _enqueue_manual_crawl(req or CrawlRunRequest())


@router.post("/crawl/retry", dependencies=[Admin])
async def retry_crawl() -> dict:
    """Re-enqueue the last interrupted list using its original crawl scope."""
    redis = await get_arq_pool()
    if await redis.exists(NOTICE_CRAWL_ACTIVE_KEY):
        raise HTTPException(status_code=409, detail="이미 크롤링이 실행 중입니다.")
    progress = await anyio.to_thread.run_sync(load_crawl_progress)
    if progress.get("status") not in {"interrupted", "failed", "stopped"}:
        raise HTTPException(status_code=409, detail="이어갈 수집 목록이 없습니다.")
    request_data = progress.get("request") or load_settings().get("crawl_request") or {}
    try:
        request = CrawlRunRequest.model_validate(request_data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="이전 수집 범위를 복원할 수 없습니다.") from exc
    result = await _enqueue_manual_crawl(request, resume=True)
    result["resumed_from"] = progress.get("job_id")
    return result


async def _active_crawl_redis():
    redis = await get_arq_pool()
    if not await redis.exists(NOTICE_CRAWL_ACTIVE_KEY):
        raise HTTPException(status_code=409, detail="현재 실행 중인 공지 수집이 없습니다.")
    return redis


@router.post("/crawl/pause", dependencies=[Admin])
async def pause_crawl() -> dict:
    redis = await _active_crawl_redis()
    if await redis.exists(NOTICE_CRAWL_STOP_KEY):
        raise HTTPException(status_code=409, detail="공지 수집을 중지하는 중입니다.")
    await redis.set(NOTICE_CRAWL_PAUSE_KEY, "1", ex=25200)
    return {"ok": True, "state": "pausing"}


@router.post("/crawl/resume", dependencies=[Admin])
async def resume_crawl() -> dict:
    redis = await _active_crawl_redis()
    await redis.delete(NOTICE_CRAWL_PAUSE_KEY)
    return {"ok": True, "state": "running"}


@router.post("/crawl/stop", dependencies=[Admin])
async def stop_crawl() -> dict:
    redis = await _active_crawl_redis()
    await redis.set(NOTICE_CRAWL_STOP_KEY, "1", ex=25200)
    await redis.delete(NOTICE_CRAWL_PAUSE_KEY)
    return {"ok": True, "state": "stopping"}


@router.post("/crawl/dismiss", dependencies=[Admin])
async def dismiss_crawl() -> dict:
    """Close an inactive run while preserving every reusable checkpoint."""
    redis = await get_arq_pool()
    if (
        await redis.exists(NOTICE_CRAWL_ACTIVE_KEY)
        or await redis.exists(NOTICE_CRAWL_PENDING_KEY)
    ):
        raise HTTPException(
            status_code=409,
            detail="실행 중인 수집은 먼저 수집 중지한 뒤 종료하세요.",
        )
    progress = await anyio.to_thread.run_sync(load_crawl_progress)
    if progress.get("status") not in {"interrupted", "failed", "stopped"}:
        raise HTTPException(status_code=409, detail="종료할 미완료 수집 작업이 없습니다.")
    progress.update({
        "status": "dismissed",
        "phase": "dismissed",
        "resumable": False,
        "dismissed_at": datetime.now(timezone.utc).isoformat(),
    })
    await anyio.to_thread.run_sync(save_crawl_progress, progress)
    await redis.delete(
        NOTICE_CRAWL_PROGRESS_KEY,
        NOTICE_CRAWL_PAUSE_KEY,
        NOTICE_CRAWL_STOP_KEY,
        NOTICE_CRAWL_PENDING_KEY,
    )
    return {
        "ok": True,
        "state": "dismissed",
        "preserved_notice_list": True,
        "preserved_checkpoints": True,
        "preserved_assets": True,
    }


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
    active = bool(await redis.exists(NOTICE_CRAWL_ACTIVE_KEY))
    pending = bool(await redis.exists(NOTICE_CRAWL_PENDING_KEY))
    paused = bool(await redis.exists(NOTICE_CRAWL_PAUSE_KEY))
    stop_requested = bool(await redis.exists(NOTICE_CRAWL_STOP_KEY))
    progress = {}
    progress = await anyio.to_thread.run_sync(load_crawl_progress)
    if not progress:
        raw_progress = await redis.get(NOTICE_CRAWL_PROGRESS_KEY)
        if raw_progress:
            try:
                progress = json.loads(raw_progress)
            except (TypeError, ValueError):
                progress = {}
    return {
        "active": active,
        "pending": pending,
        "paused": paused,
        "stop_requested": stop_requested,
        "total": row[0],
        "completed": row[1],
        "discovered": row[2],
        "failed": row[3],
        "last_seen_at": row[4],
        "run": progress,
    }


@router.post("/notices/sync-list", dependencies=[Admin])
async def sync_notice_list() -> dict:
    """6개 소스의 목록 URL만 등록하고 상세·LLM 처리는 시작하지 않는다."""
    redis = await get_arq_pool()
    if (
        await redis.exists(NOTICE_CRAWL_ACTIVE_KEY)
        or await redis.exists(NOTICE_CRAWL_PENDING_KEY)
    ):
        raise HTTPException(
            status_code=409,
            detail="공지 수집 중에는 목록을 동기화할 수 없습니다. 수집을 중지한 뒤 다시 시도하세요.",
        )
    return await anyio.to_thread.run_sync(sync_notice_lists)


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
        AND (%s = '' OR cat.name = %s)
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
            f"""SELECT count(*) FROM content n
                JOIN source s ON s.source_id=n.source_id
                JOIN category cat ON cat.category_id=n.category_id
                WHERE (%s = '%%' OR n.title ILIKE %s OR n.content ILIKE %s)
                AND {filters}""",
            (pattern, pattern, pattern, *params),
        )).fetchone())[0]
        rows = await (await conn.execute(
            f"""SELECT n.content_id, n.title, cat.name AS category, n.posted_at, n.crawled_at,
                      n.archived_at, s.name, n.url,
                      n.extraction_version,
                      {NOTICE_EMBEDDING_MODELS_SQL} AS embedding_models,
                      {NOTICE_DATABASE_BYTES_SQL} AS database_bytes,
                      {NOTICE_STORAGE_PATHS_SQL} AS storage_paths
               FROM content n
               JOIN source s ON s.source_id=n.source_id
               JOIN category cat ON cat.category_id=n.category_id
               WHERE (%s = '%%' OR n.title ILIKE %s OR n.content ILIKE %s)
               AND {filters}
               ORDER BY n.posted_at DESC NULLS LAST, n.content_id DESC LIMIT %s OFFSET %s""",
            (pattern, pattern, pattern, *params, limit, offset),
        )).fetchall()
    items = []
    keys = (
        "id", "title", "category", "posted_at", "crawled_at",
        "archived_at", "source", "url",
        "extraction_version", "embedding_models", "database_bytes", "storage_paths",
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
                   (SELECT count(*) FROM content),
                   (SELECT COALESCE(sum(pg_column_size(n)), 0) FROM content n)
                   + (SELECT COALESCE(sum(pg_column_size(a)), 0) FROM content_asset a)
                   + (SELECT COALESCE(sum(pg_column_size(p)), 0) FROM notice_period p)
                   + (SELECT COALESCE(sum(pg_column_size(aud)), 0) FROM notice_target aud)
                   + (SELECT COALESCE(sum(pg_column_size(app)), 0) FROM notice_application app)
                   + (SELECT COALESCE(sum(pg_column_size(ch)), 0) FROM content_chunk ch)"""
        )).fetchone()
        asset_row = await (await conn.execute(
            """SELECT count(*), array_agg(DISTINCT storage_path)
               FROM content_asset WHERE storage_path IS NOT NULL"""
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


@router.get("/notices/feed", dependencies=[Admin])
async def notice_feed(
    q: str = "",
    source_code: str = "",
    category: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    archive: Literal["active", "archived", "all"] = "all",
    extraction_version: str = "",
    source_kind: Literal["notice", "academic"] | None = None,
    sort: Literal["posted_desc", "posted_asc", "collected_desc", "collected_asc"] = "posted_desc",
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Return saved and discovered notices as one correctly sorted, paged feed."""
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="종료일은 시작일보다 빠를 수 없습니다.")
    pattern = f"%{q.strip()}%"
    saved_filters = """
        (%s = '%%' OR n.title ILIKE %s OR n.content ILIKE %s)
        AND (%s = '' OR s.code = %s)
        AND (%s = '' OR cat.name = %s)
        AND (%s::date IS NULL OR n.posted_at >= %s::date)
        AND (%s::date IS NULL OR n.posted_at < %s::date + INTERVAL '1 day')
        AND (%s = '' OR n.extraction_version = %s)
        AND (%s::text IS NULL OR n.content_type = %s)
        AND (%s = 'all' OR (%s = 'active' AND n.archived_at IS NULL)
             OR (%s = 'archived' AND n.archived_at IS NOT NULL))
    """
    saved_params = (
        pattern, pattern, pattern,
        source_code, source_code,
        category, category,
        date_from, date_from,
        date_to, date_to,
        extraction_version, extraction_version,
        source_kind, source_kind,
        archive, archive, archive,
    )
    registry_filters = """
        c.status <> 'completed'
        AND NOT EXISTS (SELECT 1 FROM content n2 WHERE n2.url = c.url)
        AND (%s = '%%' OR c.title ILIKE %s)
        AND (%s = '' OR s.code = %s)
        AND (%s::date IS NULL OR c.posted_at >= %s::date)
        AND (%s::date IS NULL OR c.posted_at < %s::date + INTERVAL '1 day')
        AND %s = '' AND %s = '' AND %s <> 'archived'
        AND (%s::text IS NULL OR s.kind = %s)
    """
    registry_params = (
        pattern, pattern,
        source_code, source_code,
        date_from, date_from,
        date_to, date_to,
        category, extraction_version, archive,
        source_kind, source_kind,
    )
    feed_sql = f"""
        SELECT 'stored'::text AS kind,n.content_id,n.title,cat.name AS category,n.posted_at,
               n.crawled_at AS collected_at,n.archived_at,s.name AS source,s.code AS source_code,
               n.url,n.extraction_version,
               {NOTICE_EMBEDDING_MODELS_SQL} AS embedding_models,
               ({NOTICE_DATABASE_BYTES_SQL})::bigint AS database_bytes,
               ({NOTICE_STORAGE_PATHS_SQL})::text[] AS storage_paths,
               'completed'::text AS status,'저장 완료'::text AS stage,NULL::int AS page
        FROM content n
        JOIN source s ON s.source_id=n.source_id
        JOIN category cat ON cat.category_id=n.category_id
        WHERE {saved_filters}
        UNION ALL
        SELECT 'registry'::text,NULL::bigint,c.title,NULL::text,c.posted_at,
               c.first_discovered_at,NULL::timestamptz,s.name,s.code,c.url,NULL::text,
               ARRAY[]::text[],0::bigint,ARRAY[]::text[],c.status,c.stage,c.page_number
        FROM crawl_url_state c JOIN source s ON s.source_id=c.source_id WHERE {registry_filters}
    """
    order_sql = {
        "posted_desc": "posted_at DESC NULLS LAST, collected_at DESC",
        "posted_asc": "posted_at ASC NULLS LAST, collected_at ASC",
        "collected_desc": "collected_at DESC NULLS LAST, posted_at DESC NULLS LAST",
        "collected_asc": "collected_at ASC NULLS LAST, posted_at ASC NULLS LAST",
    }[sort]
    params = (*saved_params, *registry_params)
    async with pool.connection() as conn:
        total = (await (await conn.execute(
            f"WITH feed AS ({feed_sql}) SELECT count(*) FROM feed",
            params,
        )).fetchone())[0]
        rows = await (await conn.execute(
            f"WITH feed AS ({feed_sql}) SELECT * FROM feed ORDER BY {order_sql},url ASC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )).fetchall()
    keys = (
        "kind", "id", "title", "category", "posted_at", "collected_at", "archived_at",
        "source", "source_code", "url", "extraction_version", "embedding_models",
        "database_bytes", "storage_paths", "status", "stage", "page",
    )
    items = []
    for row in rows:
        item = dict(zip(keys, row))
        file_bytes = _stored_file_bytes(item.pop("storage_paths", []))
        item["storage_bytes"] = int(item.pop("database_bytes", 0) or 0) + file_bytes
        items.append(item)
    return {"total": total, "items": items, "sort": sort}


@router.get("/notices/registry", dependencies=[Admin])
async def notice_registry(
    q: str = "",
    source_code: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Return discovered notices that have not reached the final notice table yet."""
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="종료일은 시작일보다 빠를 수 없습니다.")
    pattern = f"%{q.strip()}%"
    params = (
        pattern, pattern,
        source_code, source_code,
        date_from, date_from,
        date_to, date_to,
    )
    filters = """
        c.status <> 'completed'
        AND NOT EXISTS (SELECT 1 FROM content n WHERE n.url = c.url)
        AND (%s = '%%' OR c.title ILIKE %s)
        AND (%s = '' OR s.code = %s)
        AND (%s::date IS NULL OR c.posted_at >= %s::date)
        AND (%s::date IS NULL OR c.posted_at < %s::date + INTERVAL '1 day')
    """
    async with pool.connection() as conn:
        total = (await (await conn.execute(
            f"SELECT count(*) FROM crawl_url_state c JOIN source s ON s.source_id=c.source_id WHERE {filters}",
            params,
        )).fetchone())[0]
        rows = await (await conn.execute(
            f"""SELECT c.url,c.title,c.posted_at,c.status,c.stage,c.page_number,
                       c.updated_at,s.code,s.name
                FROM crawl_url_state c JOIN source s ON s.source_id=c.source_id
                WHERE {filters}
                ORDER BY c.posted_at DESC NULLS LAST, c.first_discovered_at DESC
                LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )).fetchall()
    keys = ("url", "title", "posted_at", "status", "stage", "page", "updated_at", "source_code", "source")
    return {"total": total, "items": [dict(zip(keys, row)) for row in rows]}


@router.get("/notices/filters", dependencies=[Admin])
async def notice_filters(
    source_kind: Literal["notice", "academic"] | None = None,
) -> dict:
    async with pool.connection() as conn:
        sources = await (await conn.execute(
            """SELECT s.code, s.name FROM source s
               WHERE (%s::text IS NULL OR s.kind=%s)
                 AND (EXISTS (SELECT 1 FROM content n WHERE n.source_id=s.source_id)
                      OR EXISTS (SELECT 1 FROM crawl_url_state c WHERE c.source_id=s.source_id))
               ORDER BY s.name""",
            (source_kind, source_kind),
        )).fetchall()
        years = await (await conn.execute(
            """SELECT DISTINCT EXTRACT(YEAR FROM posted_at)::int
               FROM content WHERE posted_at IS NOT NULL ORDER BY 1 DESC"""
        )).fetchall()
        versions = await (await conn.execute(
            """SELECT DISTINCT extraction_version FROM content
               WHERE extraction_version IS NOT NULL ORDER BY 1 DESC"""
        )).fetchall()
        embedding_models = await (await conn.execute(
            """SELECT DISTINCT embedding_provider || ' · ' || embedding_model
               FROM content_chunk ORDER BY 1"""
        )).fetchall()
    return {
        "sources": [{"code": row[0], "name": row[1]} for row in sources],
        "categories": list(NOTICE_CATEGORIES),
        "years": [row[0] for row in years],
        "extraction_versions": [row[0] for row in versions],
        "embedding_models": [row[0] for row in embedding_models],
    }


@router.get("/notices/{notice_id}", dependencies=[Admin])
async def notice_detail(notice_id: int) -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            """SELECT n.content_id,n.title,n.url,n.content,n.body_content,n.summary,cat.name,
                      n.posted_at,n.crawled_at,n.updated_at,n.extraction_version,
                      n.extra,n.archived_at,s.name,
                      """ + NOTICE_EMBEDDING_MODELS_SQL + """ AS embedding_models,
                      """ + NOTICE_DATABASE_BYTES_SQL + """ AS database_bytes,
                      """ + NOTICE_STORAGE_PATHS_SQL + """ AS storage_paths
               FROM content n
               JOIN source s ON s.source_id=n.source_id
               JOIN category cat ON cat.category_id=n.category_id
               WHERE n.content_id=%s""", (notice_id,)
        )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
        assets = await (await conn.execute(
            "SELECT asset_id,kind,filename,source_url,storage_path,mime_type,extracted_text,extra FROM content_asset WHERE content_id=%s ORDER BY order_idx,asset_id",
            (notice_id,),
        )).fetchall()
        periods = await (await conn.execute(
            "SELECT kind,starts_on,ends_on,source_text,confidence FROM notice_period WHERE notice_id=%s ORDER BY order_idx,period_id",
            (notice_id,),
        )).fetchall()
        audiences = await (await conn.execute(
            "SELECT kind,value,source_text,confidence FROM notice_target WHERE notice_id=%s ORDER BY order_idx,target_id",
            (notice_id,),
        )).fetchall()
    keys = ("id","title","url","content","body_content","summary","category","posted_at","crawled_at","updated_at","extraction_version","extra","archived_at","source","embedding_models","database_bytes","storage_paths")
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
            "SELECT storage_path,mime_type,filename FROM content_asset WHERE asset_id=%s", (asset_id,)
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


@router.get("/assets/{asset_id}/preview", dependencies=[Admin])
async def asset_preview(asset_id: int) -> dict:
    """Return a manager-only image preview without cross-origin image loading."""
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT storage_path,mime_type FROM content_asset WHERE asset_id=%s", (asset_id,)
        )).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="저장된 자산 파일을 찾을 수 없습니다.")
    mime_type = str(row[1] or "")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="미리보기를 지원하는 이미지 자산이 아닙니다.")
    path = resolve_asset_path(str(row[0]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="자산 파일이 디스크에 없습니다.")
    encoded = base64.b64encode(await anyio.Path(path).read_bytes()).decode("ascii")
    return {"data_url": f"data:{mime_type};base64,{encoded}"}


@router.get("/accounts", dependencies=[Admin])
async def list_accounts() -> dict:
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            """SELECT u.student_id,u.name,u.major,u.year,
                      COALESCE(json_agg(json_build_object(
                          'id',l.id,'provider',l.provider,'label',l.label,'model',l.model,'active',l.active
                      )) FILTER (WHERE l.id IS NOT NULL),'[]'::json),
                      u.timetable IS NOT NULL,u.grade_distribution_json IS NOT NULL,
                      u.cumulative_grades_json IS NOT NULL,u.graduation_credits IS NOT NULL,
                      (SELECT count(*) FROM lms_courses c WHERE c.student_id=u.student_id),
                      (SELECT count(*) FROM lms_tasks t WHERE t.student_id=u.student_id)
               FROM users u LEFT JOIN student_llm_account l ON l.student_id=u.student_id
               GROUP BY u.student_id ORDER BY u.student_id"""
        )).fetchall()
    keys = ("student_id","name","major","year","llm_accounts",
            "has_timetable","has_grade_distribution","has_cumulative_grades",
            "has_graduation_credits","lms_course_count","lms_task_count")
    return {"items": [dict(zip(keys, row)) for row in rows]}


@router.get("/accounts/{student_id}/portal-data", dependencies=[Admin])
async def account_portal_data(student_id: str) -> dict:
    """Read one student's stored portal/LMS data, excluding sessions and credentials."""
    async with pool.connection() as conn:
        user = await (await conn.execute(
            """SELECT student_id,name,major,year,interests,favorite_courses,
                      graduation_credits,timetable,grade_distribution_json,cumulative_grades_json
               FROM users WHERE student_id=%s""", (student_id,)
        )).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        courses = await (await conn.execute(
            "SELECT course_id,course_name,synced_at FROM lms_courses WHERE student_id=%s ORDER BY course_name",
            (student_id,),
        )).fetchall()
        tasks = await (await conn.execute(
            """SELECT task_type,title,course_name,due_date,progress,url,is_done,source,synced_at
               FROM lms_tasks WHERE student_id=%s ORDER BY due_date NULLS LAST,created_at DESC""",
            (student_id,),
        )).fetchall()
    keys = ("student_id","name","major","year","interests","favorite_courses",
            "graduation_credits","timetable","grade_distribution","cumulative_grades")
    result = dict(zip(keys, user))
    for field in ("interests", "favorite_courses"):
        result[field] = [item.strip() for item in (result[field] or "").split(",") if item.strip()]
    result["lms_courses"] = [dict(zip(("course_id","course_name","synced_at"), row)) for row in courses]
    result["lms_tasks"] = [dict(zip(("task_type","title","course_name","due_date","progress",
                                     "url","is_done","source","synced_at"), row)) for row in tasks]
    return result


@router.delete("/accounts/{student_id}/llm/{account_id}", dependencies=[Admin])
async def remove_student_llm_account(student_id: str, account_id: str) -> dict:
    from api.student_llm import delete_account
    try:
        removed = await delete_account(student_id, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="잘못된 계정 ID입니다.") from exc
    if not removed:
        raise HTTPException(status_code=404, detail="학생의 LLM 계정을 찾을 수 없습니다.")
    return {"deleted": True}


@router.put("/accounts/{student_id}", dependencies=[Admin])
async def update_account(student_id: str, req: UserAccountUpdate) -> dict:
    async with pool.connection() as conn:
        current = await (await conn.execute(
            "SELECT 1 FROM users WHERE student_id=%s", (student_id,)
        )).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        await conn.execute(
            "UPDATE users SET name=%s,major=%s,year=%s WHERE student_id=%s",
            (req.name, req.major, req.year, student_id),
        )
        await conn.commit()
    return {"ok": True}


@router.delete("/accounts/{student_id}", dependencies=[Admin])
async def delete_account(student_id: str) -> dict:
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "DELETE FROM users WHERE student_id=%s RETURNING student_id", (student_id,)
        )).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        await conn.commit()
    from api.sessions import delete_portal_session

    await anyio.to_thread.run_sync(delete_portal_session, student_id)
    return {"ok": True}
