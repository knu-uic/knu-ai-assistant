from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from functools import lru_cache
from dotenv import load_dotenv
import os

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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_llm_context_window_tokens() -> int:
    """현재 LLM의 컨텍스트 윈도우 토큰 수.

    LM Studio에서 모델을 바꾸면 .env의 LLM_CONTEXT_WINDOW_TOKENS만 같이 바꾸면
    refine/answer 입력 예산이 같은 비율로 따라간다.
    """
    return _env_int("LLM_CONTEXT_WINDOW_TOKENS", 8192)


def get_llm_context_char_budget(
    env_name: str,
    *,
    ratio_multiplier: float = 1.0,
    min_chars: int = 1000,
) -> int:
    """LLM 컨텍스트 윈도우를 문자 예산으로 근사한다.

    기본값: context_window_tokens * LLM_CONTEXT_USAGE_RATIO * LLM_CHARS_PER_TOKEN.
    한국어/혼합 텍스트는 토크나이저마다 편차가 있어 보수적 근사값을 쓴다.
    개별 예산은 env_name으로 직접 override 가능하다.
    """
    override = os.getenv(env_name)
    if override and override.strip():
        try:
            return max(min_chars, int(override))
        except ValueError:
            pass

    tokens = get_llm_context_window_tokens()
    usage_ratio = _env_float("LLM_CONTEXT_USAGE_RATIO", 0.8)
    chars_per_token = _env_float("LLM_CHARS_PER_TOKEN", 1.4)
    budget = int(tokens * usage_ratio * chars_per_token * ratio_multiplier)
    return max(min_chars, budget)


def get_answer_context_char_budget() -> int:
    return get_llm_context_char_budget("ANSWER_CONTEXT_CHAR_BUDGET")


def get_refine_full_content_limit() -> int:
    ratio = _env_float("REFINE_CONTEXT_RATIO_MULTIPLIER", 0.35)
    return get_llm_context_char_budget(
        "REFINE_FULL_CONTENT_LIMIT",
        ratio_multiplier=ratio,
    )


def get_attachment_name_reserve() -> int:
    override = os.getenv("ATTACHMENT_NAME_RESERVE")
    if override and override.strip():
        try:
            return max(0, int(override))
        except ValueError:
            pass
    ratio = _env_float("ATTACHMENT_NAME_RESERVE_RATIO", 0.13)
    return max(0, int(get_answer_context_char_budget() * ratio))


def get_llm():
    vlm_provider = os.getenv("VLM_PROVIDER")
    llm_model = os.getenv("LLM_MODEL")
    lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL")

    if vlm_provider == "google":
        return ChatGoogleGenerativeAI(
            model=llm_model,
            google_api_key=(
                os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            ),
            temperature=0,
        )

    if vlm_provider == "openai":
        return ChatOpenAI(
            model=llm_model,
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )

    if vlm_provider == "lmstudio":
        return ChatOpenAI(
            model=llm_model,
            base_url=lmstudio_base_url,
            api_key="lm-studio",
            temperature=0,
        )

    raise ValueError(f"지원하지 않는 provider: {vlm_provider}")

@lru_cache(maxsize=1)
def get_embeddings():
    embedding_provider = os.getenv("EMBEDDING_PROVIDER")
    embedding_model = os.getenv("EMBEDDING_MODEL")
    lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL")

    if embedding_provider == "google":
        return GoogleGenerativeAIEmbeddings(
            model=embedding_model,
            output_dimensionality=EMBEDDING_DIM,
        )

    if embedding_provider == "openai":
        return OpenAIEmbeddings(
            model=embedding_model,
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if embedding_provider == "lmstudio":
        return OpenAIEmbeddings(
            model=embedding_model,
            base_url=lmstudio_base_url,
            api_key="lm-studio",
            check_embedding_ctx_length=False,
        )

    raise ValueError(
        f"지원하지 않는 provider: {embedding_provider}"
    )
    

@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(
        os.getenv("RERANKER_MODEL"),
        max_length=os.getenv("RERANKER_MAX_LENGTH"),
    )
