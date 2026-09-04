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
from api.runtime_settings import load_settings
from api.codex_oauth import codex_response

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



def _active_vlm() -> dict:
    return load_settings()["vlm"]


@lru_cache(maxsize=12)
def _vlm_client(provider: str, model: str, base_url: str, api_key: str):
    """설정 조합별 LangChain 클라이언트. 설정 변경 시 새 키로 자동 교체된다."""
    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0)
    if provider in {"lmstudio", "ollama"}:
        default_url = "http://127.0.0.1:11434/v1" if provider == "ollama" else "http://127.0.0.1:1234/v1"
        return ChatOpenAI(
            model=model,
            base_url=base_url or default_url,
            api_key=api_key or "local",
            temperature=0,
            max_tokens=_env_int("LOCAL_LLM_MAX_TOKENS", 2048),
            timeout=_env_int("LOCAL_LLM_TIMEOUT_SECONDS", 180),
        )
    return ChatOpenAI(model=model, api_key=api_key, temperature=0)


def _vlm_image_block(data_url: str, provider: str) -> dict:
    """provider별 langchain image block 포맷."""
    if provider != "google":
        return {"type": "image_url", "image_url": {"url": data_url}}
    return {"type": "image_url", "image_url": data_url}


def image_to_text(image_bytes: bytes, mime: str, prompt: str, model: str = LLM_MODEL) -> str:
    """이미지 bytes를 VLM에 던져 텍스트로 받는다."""
    settings = _active_vlm()
    active_model = settings["model"] or model
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    if settings["provider"] == "openai-codex":
        return codex_response(prompt, model=active_model, image_data_url=data_url)
    msg = HumanMessage(content=[
        {"type": "text", "text": prompt},
        _vlm_image_block(data_url, settings["provider"]),
    ])
    response = _vlm_client(
        settings["provider"], active_model, settings["base_url"], settings["api_key"]
    ).invoke([msg])
    return response.content if isinstance(response.content, str) else str(response.content)


def get_llm():
    settings = _active_vlm()
    provider = settings["provider"]
    model = settings["model"] or LLM_MODEL
    api_key = settings["api_key"]
    if provider == "openai-codex":
        # Codex 선택은 OCR/VLM 이미지 추출에만 적용하고, 공지 구조화와
        # RAG 답변은 기존 서버 LLM 설정을 유지한다.
        provider = {"local": "lmstudio", "openai-api": "openai", "gemini": "google"}.get(
            (VLM_PROVIDER or "local").lower(), (VLM_PROVIDER or "local").lower()
        )
        model = LLM_MODEL
        api_key = GOOGLE_API_KEY if provider == "google" else OPENAI_API_KEY
    if provider == "google":
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0,
        )

    if provider == "openai":
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=0,
        )

    if provider in {"lmstudio", "ollama"}:
        default_url = "http://127.0.0.1:11434/v1" if provider == "ollama" else OPENAI_COMPAT_BASE_URL
        return ChatOpenAI(
            model=model,
            base_url=settings["base_url"] or default_url,
            api_key=api_key or "local",
            # 구조화 추출은 재현성과 사실 보존이 중요하므로 기본값을 최저로 둔다.
            temperature=_env_float("LOCAL_LLM_TEMPERATURE", 0.0),
            # Gemma 계열 chat template가 지원하는 내부 추론은 공지 구조화에는
            # 불필요하다. LM Studio가 모델 기본값으로 thinking을 켜더라도
            # 명시적으로 비활성화해 수집 지연과 불필요한 token 소비를 막는다.
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": False,
                },
            },
            # OpenAI-compatible local models do not always emit a stop token
            # reliably for OCR/structured-output requests. Without a limit,
            # one malformed response can occupy LM Studio until its full
            # context window is exhausted and stall the entire ingest worker.
            max_tokens=_env_int("LOCAL_LLM_MAX_TOKENS", 2048),
            timeout=_env_int("LOCAL_LLM_TIMEOUT_SECONDS", 180),
        )

    raise ValueError(f"지원하지 않는 provider: {provider}")


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
