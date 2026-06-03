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
    60000,
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
    12000,
)

# body가 충분하면 attachment 원문은 refine에서 거의 사용 안 함.
BODY_MIN_FOR_ATTACHMENT_SKIP = 1000

# body가 빈약할 때 attachment excerpt fallback budget.
ATTACHMENT_REFINE_FALLBACK_CHARS = 10000


# -----------------------------
# crawling
# -----------------------------

MAX_CRAWL_WORKERS = _env_int(
    "MAX_CRAWL_WORKERS",
    4,
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
