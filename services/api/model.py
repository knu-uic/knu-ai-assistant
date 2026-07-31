import base64
import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from config import (
    CONTEXT_WINDOW_CHARS,
    REFINE_FULL_CONTENT_LIMIT,
    RERANKER_MAX_LENGTH,
    ATTACHMENT_NAME_RESERVE_RATIO,
    VLM_PROVIDER,
    LLM_MODEL,
    OPENAI_COMPAT_BASE_URL,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    RERANKER_MODEL,
)

load_dotenv()

# 임베딩 벡터 차원 수(pgvector schema와 반드시 동일해야 하며, embedding model 변경 시 함께 수정)
_embedding_dim_raw = os.getenv("EMBEDDING_DIM")
if not _embedding_dim_raw or not _embedding_dim_raw.strip().isdigit():
    raise RuntimeError(
        "EMBEDDING_DIM 환경변수가 없거나 정수가 아닙니다 "
        f"(현재 값: {_embedding_dim_raw!r}). "
        "pgvector 스키마의 벡터 차원과 동일한 정수로 .env에 설정하세요."
    )
EMBEDDING_DIM = int(_embedding_dim_raw)

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
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(
        RERANKER_MODEL,
        max_length=RERANKER_MAX_LENGTH,
    )


# ── VLM 이미지 → 텍스트 유틸 ────────────────────────────────────
# curriculum.py 등 이미지를 VLM에 넘기는 파서들이 공통으로 사용.



@lru_cache(maxsize=4)
def _vlm_client(model: str):
    """모델별 LangChain Chat 클라이언트 캐시. provider 토글 따름."""
    if VLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=OPENAI_API_KEY, temperature=0)
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, google_api_key=GOOGLE_API_KEY, temperature=0)


def _vlm_image_block(data_url: str) -> dict:
    """provider별 langchain image block 포맷."""
    if VLM_PROVIDER == "openai":
        return {"type": "image_url", "image_url": {"url": data_url}}
    return {"type": "image_url", "image_url": data_url}


def image_to_text(image_bytes: bytes, mime: str, prompt: str, model: str = LLM_MODEL) -> str:
    """이미지 bytes를 VLM에 던져 텍스트로 받는다."""
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    msg = HumanMessage(content=[
        {"type": "text", "text": prompt},
        _vlm_image_block(data_url),
    ])
    response = _vlm_client(model).invoke([msg])
    return response.content if isinstance(response.content, str) else str(response.content)


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

    if VLM_PROVIDER == "local":
        return ChatOpenAI(
            model=LLM_MODEL,
            base_url=OPENAI_COMPAT_BASE_URL,
            api_key="lm-studio",
            # 구조화 추출은 재현성과 사실 보존이 중요하므로 기본값을 최저로 둔다.
            temperature=_env_float("LOCAL_LLM_TEMPERATURE", 0.0),
            # OpenAI-compatible local models do not always emit a stop token
            # reliably for OCR/structured-output requests. Without a limit,
            # one malformed response can occupy LM Studio until its full
            # context window is exhausted and stall the entire ingest worker.
            max_tokens=_env_int("LOCAL_LLM_MAX_TOKENS", 2048),
            timeout=_env_int("LOCAL_LLM_TIMEOUT_SECONDS", 180),
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

    if EMBEDDING_PROVIDER == "local":
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OPENAI_COMPAT_BASE_URL,
            api_key="lm-studio",
            check_embedding_ctx_length=False,
        )

    raise ValueError(
        f"지원하지 않는 provider: {EMBEDDING_PROVIDER}"
    )
