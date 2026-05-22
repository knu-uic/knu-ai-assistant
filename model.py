from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from functools import lru_cache
from dotenv import load_dotenv
import os
from config import (
    CONTEXT_WINDOW_CHARS,
    REFINE_FULL_CONTENT_LIMIT,
    RERANKER_MAX_LENGTH,
    ATTACHMENT_NAME_RESERVE_RATIO,
    VLM_PROVIDER,
    LLM_MODEL,
    LMSTUDIO_BASE_URL,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    RERANKER_MODEL,
)

load_dotenv()

# 임베딩 벡터 차원 수(pgvector schema와 반드시 동일해야 하며, embedding model 변경 시 함께 수정)
EMBEDDING_DIM = 768


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def get_context_window_chars() -> int:
    """config.py compatibility wrapper."""
    return CONTEXT_WINDOW_CHARS


def get_llm_context_char_budget(
    env_name: str,
    *,
    default: int,
    min_chars: int = 1000,
) -> int:
    """RAG 입력용 문자 예산을 환경변수 기반으로 반환한다.

    실제 모델 context window(LM Studio 설정)와
    앱의 stuffing budget을 분리하기 위해 직접 문자 수를 관리한다.
    """
    return max(
        min_chars,
        _env_int(env_name, default),
    )


@lru_cache(maxsize=1)
def get_answer_context_char_budget() -> int:
    return get_llm_context_char_budget(
        "ANSWER_CONTEXT_CHAR_BUDGET",
        default=6000,
    )


def get_refine_full_content_limit() -> int:
    return REFINE_FULL_CONTENT_LIMIT


def get_attachment_name_reserve() -> int:
    override = os.getenv("ATTACHMENT_NAME_RESERVE")
    if override and override.strip():
        try:
            return max(0, int(override))
        except ValueError:
            pass
    ratio = ATTACHMENT_NAME_RESERVE_RATIO
    return max(0, int(get_answer_context_char_budget() * ratio))


@lru_cache(maxsize=1)
def get_llm():
    if VLM_PROVIDER == "google":
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0,
        )

    if VLM_PROVIDER == "openai":
        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=0,
        )

    if VLM_PROVIDER == "lmstudio":
        return ChatOpenAI(
            model=LLM_MODEL,
            base_url=LMSTUDIO_BASE_URL,
            api_key="lm-studio",
            temperature=0,
            max_tokens=None,
        )

    raise ValueError(f"지원하지 않는 provider: {VLM_PROVIDER}")


@lru_cache(maxsize=1)
def get_embeddings():
    if EMBEDDING_PROVIDER == "google":
        return GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            output_dimensionality=EMBEDDING_DIM,
        )

    if EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            api_key=OPENAI_API_KEY,
        )

    if EMBEDDING_PROVIDER == "lmstudio":
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=LMSTUDIO_BASE_URL,
            api_key="lm-studio",
            check_embedding_ctx_length=False,
        )

    raise ValueError(
        f"지원하지 않는 provider: {EMBEDDING_PROVIDER}"
    )
    

@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(
        RERANKER_MODEL,
        max_length=RERANKER_MAX_LENGTH,
    )