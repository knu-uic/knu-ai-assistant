"""애플리케이션 전역 runtime configuration.

원칙:
- 모든 env parsing 중앙화
- 타입 변환/기본값 처리 통합
- derived config 제공
- retrieval/refine budget 계산 공통화
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import os


# -----------------------------
# runtime environment
# -----------------------------

RUNTIME_ENV = (
    os.getenv("RUNTIME_ENV", "local")
    .strip()
    .lower()
)

LOCAL_LLM_PORT = os.getenv(
    "LOCAL_LLM_PORT",
    "1234",
).strip()

if RUNTIME_ENV == "docker":
    DB_HOST = "db"

    OPENAI_COMPAT_BASE_URL = (
        f"http://host.docker.internal:{LOCAL_LLM_PORT}/v1"
    )

else:
    DB_HOST = "localhost"

    OPENAI_COMPAT_BASE_URL = (
        f"http://localhost:{LOCAL_LLM_PORT}/v1"
    )

# -----------------------------
# env helpers
# -----------------------------

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or raw.strip() == "":
        return default

    try:
        return int(raw)
    except ValueError:
        return default



def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)

    if raw is None or raw.strip() == "":
        return default

    try:
        return float(raw)
    except ValueError:
        return default



def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# -----------------------------
# llm / context
# -----------------------------

LLM_MAX_CONTEXT_WINDOW_TOKENS = _env_int(
    "LLM_MAX_CONTEXT_WINDOW_TOKENS",
    32768,
)

LLM_CHARS_PER_TOKEN = _env_float(
    "LLM_CHARS_PER_TOKEN",
    1.5,
)

CONTEXT_WINDOW_CHARS = max(
    4000,
    int(
        LLM_MAX_CONTEXT_WINDOW_TOKENS
        * LLM_CHARS_PER_TOKEN
    ),
)


# -----------------------------
# retrieval
# -----------------------------

RERANK_CANDIDATES = _env_int(
    "RERANK_CANDIDATES",
    50,
)

RERANK_TOP_N = _env_int(
    "RERANK_TOP_N",
    5,
)

SUPPORT_DOC_TOP_N = _env_int(
    "SUPPORT_DOC_TOP_N",
    3,
)

BROAD_RERANK_CANDIDATES = _env_int(
    "BROAD_RERANK_CANDIDATES",
    50,
)

BROAD_DOC_TOP_N = _env_int(
    "BROAD_DOC_TOP_N",
    12,
)


# -----------------------------
# refine
# -----------------------------

REFINE_FULL_CONTENT_LIMIT = _env_int(
    "REFINE_FULL_CONTENT_LIMIT",
    24000,
)

# body가 충분하면 attachment 원문은 refine에서 거의 사용 안 함.
BODY_MIN_FOR_ATTACHMENT_SKIP = 1000

# body가 빈약할 때 attachment excerpt fallback budget.
ATTACHMENT_REFINE_FALLBACK_CHARS = _env_int(
    "ATTACHMENT_REFINE_FALLBACK_CHARS",
    16000,
)


# -----------------------------
# crawling
# -----------------------------

MAX_CRAWL_WORKERS = _env_int(
    "MAX_CRAWL_WORKERS",
    4,
)
CRAWL_HTTP_TIMEOUT_SECONDS = _env_int(
    "CRAWL_HTTP_TIMEOUT_SECONDS",
    75,
)
CRAWL_HTTP_MAX_ATTEMPTS = _env_int(
    "CRAWL_HTTP_MAX_ATTEMPTS",
    3,
)
CRAWL_HTTP_BACKOFF_SECONDS = _env_int(
    "CRAWL_HTTP_BACKOFF_SECONDS",
    3,
)
ATTACHMENT_DOWNLOAD_RETRY_ATTEMPTS = _env_int(
    "ATTACHMENT_DOWNLOAD_RETRY_ATTEMPTS",
    3,
)
ATTACHMENT_DOWNLOAD_BACKOFF_SECONDS = _env_int(
    "ATTACHMENT_DOWNLOAD_BACKOFF_SECONDS",
    3,
)


# -----------------------------
# answer / verifier
# -----------------------------

ANSWER_CONTEXT_BUDGET_RATIO = _env_float(
    "ANSWER_CONTEXT_BUDGET_RATIO",
    0.70,
)

VERIFIER_CONTEXT_BUDGET_RATIO = _env_float(
    "VERIFIER_CONTEXT_BUDGET_RATIO",
    0.20,
)

ENABLE_VERIFIER = _env_bool(
    "ENABLE_VERIFIER",
    False,
)


# -----------------------------
# providers
# -----------------------------

VLM_PROVIDER = os.getenv("VLM_PROVIDER")
LLM_MODEL = os.getenv("LLM_MODEL")

GOOGLE_API_KEY = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GEMINI_API_KEY")
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")

RERANKER_PROVIDER = os.getenv("RERANKER_PROVIDER")
if not RERANKER_PROVIDER:
    if os.getenv("JINA_API_KEY"):
        RERANKER_PROVIDER = "jina"
    else:
        RERANKER_PROVIDER = "local"

RERANKER_MODEL = os.getenv("RERANKER_MODEL")

RERANKER_MAX_LENGTH = _env_int(
    "RERANKER_MAX_LENGTH",
    512,
)

ATTACHMENT_NAME_RESERVE_RATIO = _env_float(
    "ATTACHMENT_NAME_RESERVE_RATIO",
    0.13,
)

# -----------------------------
# auth
# -----------------------------

AUTH_JWT_SECRET = os.getenv("AUTH_JWT_SECRET")

MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN")
RATE_LIMIT_MCP = os.getenv("RATE_LIMIT_MCP", "60/minute")

# -----------------------------
# mail (가입 인증)
# -----------------------------

MAIL_PROVIDER = (
    os.getenv("MAIL_PROVIDER", "gmail")
    .strip()
    .lower()
)

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")

MAIL_FROM = os.getenv("MAIL_FROM") or GMAIL_USER

SIGNUP_EMAIL_DOMAIN = (
    os.getenv("SIGNUP_EMAIL_DOMAIN", "smail.kongju.ac.kr")
    .strip()
    .lower()
)

# -----------------------------
# app version (APK 직배포 강제 업데이트)
# -----------------------------

# 이 버전 미만 앱은 시작 시 업데이트 안내를 띄운다. 올릴 때는 env 변경 + 재시작.
MIN_APP_VERSION = os.getenv("MIN_APP_VERSION", "1.0.0").strip()

# -----------------------------
# rate limit
# -----------------------------

# 있으면 slowapi 저장소로 Redis 사용(다중 프로세스 대응). 없으면 in-memory.
REDIS_URL = os.getenv("REDIS_URL")

# -----------------------------
# worker (백그라운드 잡)
# -----------------------------

# 실제 주기는 Server Manager JSON을 worker가 동적으로 읽는다.
# 이 값은 기존 배포 호환을 위한 fallback이다.
NOTICE_POLL_MINUTES = _env_int("NOTICE_POLL_MINUTES", 20)

# 포털 비밀번호 잡 전달용 Fernet 키. 생성:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PORTAL_SYNC_ENC_KEY = os.getenv("PORTAL_SYNC_ENC_KEY")

# 포털 동기화 잡 제한 시간(초). Playwright 로그인+파싱 전체.
PORTAL_SYNC_TIMEOUT_SECONDS = _env_int("PORTAL_SYNC_TIMEOUT_SECONDS", 180)

# LMS 세션(쿠키+토큰) Redis 보관 기간(일). 만료 시 다음 동기화에 비번 재제출 필요.
LMS_SESSION_TTL_DAYS = _env_int("LMS_SESSION_TTL_DAYS", 7)

# 웹 SPA CORS 허용 오리진(콤마 구분). 비면 CORS 미들웨어 미적용(개발=vite proxy).
WEB_CORS_ORIGINS = [
    o.strip() for o in os.getenv("WEB_CORS_ORIGINS", "").split(",") if o.strip()
]

RATE_LIMIT_SIGNUP_REQUEST = os.getenv("RATE_LIMIT_SIGNUP_REQUEST", "3/minute")
RATE_LIMIT_AUTH = os.getenv("RATE_LIMIT_AUTH", "10/minute")
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "5/minute;150/day")
RATE_LIMIT_READ = os.getenv("RATE_LIMIT_READ", "30/minute")
# 잡 상태 폴링(2초 간격 폴링 허용 여유)
RATE_LIMIT_POLL = os.getenv("RATE_LIMIT_POLL", "120/minute")

# 공지 목록·홈 추천에서 숨길 정적 안내 페이지 소스 코드.
# (커리큘럼표·장학 안내 같은 상시 정적문서 — 검색(search_chunks)에서는 노출 유지)
HIDDEN_NOTICE_SOURCE_CODES = frozenset(
    c.strip()
    for c in os.getenv(
        "HIDDEN_NOTICE_SOURCE_CODES",
        "cse_curriculum,business_curriculum,scholarship_info",
    ).split(",")
    if c.strip()
)

# -----------------------------
# validation
# -----------------------------

if RERANK_TOP_N > RERANK_CANDIDATES:
    raise ValueError(
        "RERANK_TOP_N cannot exceed RERANK_CANDIDATES"
    )

if SUPPORT_DOC_TOP_N < 1:
    raise ValueError(
        "SUPPORT_DOC_TOP_N must be >= 1"
    )
