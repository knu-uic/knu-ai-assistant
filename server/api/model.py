import base64
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from functools import lru_cache
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel, ValidationError
from config import (
    CONTEXT_WINDOW_CHARS,
    REFINE_FULL_CONTENT_LIMIT,
    ATTACHMENT_NAME_RESERVE_RATIO,
    VLM_PROVIDER,
    LLM_MODEL,
    OPENAI_COMPAT_BASE_URL,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    VLM_MAX_OUTPUT_TOKENS,
    VLM_CONTEXT_WINDOW_TOKENS,
    VLM_TIMEOUT_SECONDS,
    LOCAL_LLM_TIMEOUT_SECONDS,
)
from api.runtime_settings import load_settings
from api.codex_oauth import codex_response
from process_lock import exclusive_file_lock

load_dotenv()

_LOGGER = logging.getLogger(__name__)
_LOCAL_INFERENCE_THREAD_LOCK = threading.RLock()
_LOCAL_INFERENCE_LOCK_PATH = Path(tempfile.gettempdir()) / "knu-local-inference.lock"


@contextmanager
def local_inference_slot(provider: str | None = None):
    """Serialize local Ollama/LM Studio inference across worker and API processes."""
    active_provider = str(
        provider or load_settings().get("vlm", {}).get("provider") or ""
    ).lower()
    if active_provider not in {"ollama", "lmstudio", "local"}:
        yield
        return
    with _LOCAL_INFERENCE_THREAD_LOCK:
        with exclusive_file_lock(_LOCAL_INFERENCE_LOCK_PATH):
            yield

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


@lru_cache(maxsize=2)
def _get_reranker(model_name: str, max_length: int):
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(
        model_name,
        max_length=max_length,
        local_files_only=True,
    )


def clear_reranker_cache() -> None:
    _get_reranker.cache_clear()


# ── VLM 이미지 → 텍스트 유틸 ────────────────────────────────────
# curriculum.py 등 이미지를 VLM에 넘기는 파서들이 공통으로 사용.



def _active_vlm() -> dict:
    return load_settings()["vlm"]


def _local_extra_body(provider: str) -> dict:
    """Return the provider-native switch that disables extraction reasoning."""
    if provider == "ollama":
        # Ollama's OpenAI-compatible endpoint maps this top-level field to
        # `think: false`. `chat_template_kwargs` is an LM Studio option and is
        # ignored by Ollama, which otherwise enables thinking by default.
        return {"reasoning_effort": "none"}
    return {"chat_template_kwargs": {"enable_thinking": False}}


class ImageOutputError(ValueError):
    """Image extraction failed; partial output must not be indexed."""


class ImageOutputTruncated(ImageOutputError):
    """The model hit its output cap rather than completing its response."""


class ImageAnalysisTimeout(ImageOutputError):
    """The image request exceeded its inference deadline."""


class _OllamaChatOpenAI(ChatOpenAI):
    """Ollama accepts max_tokens, not LangChain's max_completion_tokens."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload


def _ollama_chat_url(base_url: str) -> str:
    parts = urlsplit(base_url or "http://127.0.0.1:11434/v1")
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/api/chat", parts.query, ""))


async def _ollama_image_request(settings: dict, model: str, image_b64: str, prompt: str) -> str:
    # A single native message avoids the OpenAI adapter splitting text/image
    # into separate messages. num_ctx bounds the KV cache, including for Qwen.
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": True,
        "think": False,
        "truncate": False,
        "options": {
            "num_predict": VLM_MAX_OUTPUT_TOKENS,
            "num_ctx": VLM_CONTEXT_WINDOW_TOKENS,
            "temperature": 0,
            "top_p": 1,
            "repeat_penalty": 1,
            "presence_penalty": 0,
            "frequency_penalty": 0,
        },
    }
    headers = {}
    if settings.get("api_key"):
        headers["Authorization"] = f"Bearer {settings['api_key']}"

    async def request():
        output: list[str] = []
        async with httpx.AsyncClient(timeout=VLM_TIMEOUT_SECONDS, headers=headers) as client:
            async with client.stream("POST", _ollama_chat_url(settings.get("base_url", "")), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get("error"):
                        raise ImageOutputError("Ollama image response failed")
                    message = event.get("message") or {}
                    content = message.get("content", "")
                    if not isinstance(content, str):
                        raise ImageOutputError("Invalid Ollama image content")
                    output.append(content)
                    if event.get("done"):
                        if event.get("done_reason") == "length":
                            raise ImageOutputTruncated("Image output reached its token limit")
                        if event.get("done_reason") != "stop":
                            raise ImageOutputError("Image response did not finish normally")
                        if isinstance(event.get("eval_count"), int) and event["eval_count"] > VLM_MAX_OUTPUT_TOKENS:
                            raise ImageOutputError("Image provider exceeded the requested token limit")
                        text = "".join(output).strip()
                        if not text:
                            raise ImageOutputError("Empty image response")
                        _LOGGER.info(
                            "Image extraction completed: provider=ollama model=%s output_tokens=%s prompt_tokens=%s",
                            model, event.get("eval_count"), event.get("prompt_eval_count"),
                        )
                        return text
        raise ImageOutputError("Image stream ended without a completion event")

    try:
        # Total deadline includes model loading, prefill and streaming, not the
        # wait for the shared inference lock. Cancellation closes the stream.
        return await asyncio.wait_for(request(), timeout=VLM_TIMEOUT_SECONDS)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ImageAnalysisTimeout("Image analysis exceeded its time limit") from exc
    except httpx.HTTPStatusError as exc:
        raise ImageOutputError(f"Image provider returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, json.JSONDecodeError, AttributeError) as exc:
        raise ImageOutputError("Invalid or interrupted image response") from exc


def _ollama_image_to_text(settings: dict, model: str, image_b64: str, prompt: str) -> str:
    # The synchronous extractor can also be called by an async worker. Run the
    # cancellable HTTP request on its own loop without nesting asyncio.run().
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(
            asyncio.run, _ollama_image_request(settings, model, image_b64, prompt)
        ).result()


@lru_cache(maxsize=12)
def _vlm_client(provider: str, model: str, base_url: str, api_key: str):
    """설정 조합별 LangChain 클라이언트. 설정 변경 시 새 키로 자동 교체된다."""
    if provider == "google":
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=api_key, temperature=0,
            max_output_tokens=VLM_MAX_OUTPUT_TOKENS, timeout=VLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
    if provider in {"lmstudio", "ollama"}:
        default_url = "http://127.0.0.1:11434/v1" if provider == "ollama" else "http://127.0.0.1:1234/v1"
        client_class = _OllamaChatOpenAI if provider == "ollama" else ChatOpenAI
        return client_class(
            model=model,
            base_url=base_url or default_url,
            api_key=api_key or "local",
            temperature=0,
            max_tokens=VLM_MAX_OUTPUT_TOKENS,
            timeout=VLM_TIMEOUT_SECONDS,
            max_retries=0,
            extra_body=_local_extra_body(provider),
        )
    return ChatOpenAI(
        model=model, api_key=api_key, temperature=0,
        max_tokens=VLM_MAX_OUTPUT_TOKENS, timeout=VLM_TIMEOUT_SECONDS, max_retries=0,
    )


def _vlm_image_block(data_url: str, provider: str) -> dict:
    """provider별 langchain image block 포맷."""
    if provider != "google":
        return {"type": "image_url", "image_url": {"url": data_url}}
    return {"type": "image_url", "image_url": data_url}


def image_to_text(image_bytes: bytes, mime: str, prompt: str, model: str = LLM_MODEL) -> str:
    """이미지 bytes를 VLM에 던져 텍스트로 받는다."""
    settings = _active_vlm()
    active_model = settings["model"] or model
    image_b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{mime};base64,{image_b64}"
    if settings["provider"] == "openai-codex":
        return codex_response(prompt, model=active_model, image_data_url=data_url)
    msg = HumanMessage(content=[
        {"type": "text", "text": prompt},
        _vlm_image_block(data_url, settings["provider"]),
    ])
    with local_inference_slot(settings["provider"]):
        if settings["provider"] == "ollama":
            return _ollama_image_to_text(settings, active_model, image_b64, prompt)
        response = _vlm_client(
            settings["provider"], active_model, settings["base_url"], settings["api_key"]
        ).invoke([msg])
    reason = str(response.response_metadata.get("finish_reason", "")).upper()
    if reason in {"LENGTH", "MAX_TOKENS", "FINISHREASON.MAX_TOKENS"}:
        raise ImageOutputTruncated("Image output reached its token limit")
    text = response.content if isinstance(response.content, str) else str(response.content)
    if not text.strip():
        raise ImageOutputError("Empty image response")
    return text


def get_llm():
    settings = _active_vlm()
    provider = settings["provider"]
    if provider == "openai-codex":
        # Codex 선택은 OCR/VLM 이미지 추출에만 적용하고, 공지 구조화와
        # RAG 답변은 기존 서버 LLM 설정을 유지한다.
        provider = {"local": "lmstudio", "openai-api": "openai", "gemini": "google"}.get(
            (VLM_PROVIDER or "local").lower(), (VLM_PROVIDER or "local").lower()
        )
        settings = {
            **settings,
            "provider": provider,
            "model": LLM_MODEL,
            "api_key": GOOGLE_API_KEY if provider == "google" else OPENAI_API_KEY,
        }
    return _text_llm(settings)


def get_refine_llm():
    """Use the independently configured notice-refinement model."""
    settings = load_settings()["refine"]
    if settings["provider"] == "openai-codex":
        return _CodexRefineClient(settings["model"])
    return _text_llm(settings)


class RefineOutputError(ValueError):
    """A model response could not be validated as notice metadata."""


class _CodexRefineClient:
    def __init__(self, model: str):
        self.model = model

    def with_structured_output(self, schema: type[BaseModel], **_kwargs):
        return _CodexStructuredRefine(self.model, schema)


class _CodexStructuredRefine:
    def __init__(self, model: str, schema: type[BaseModel]):
        self.model = model
        self.schema = schema

    def invoke(self, messages: list) -> BaseModel:
        system_text = "\n\n".join(
            str(message.content) for message in messages if isinstance(message, SystemMessage)
        )
        prompt = "\n\n".join(
            str(message.content) for message in messages if not isinstance(message, SystemMessage)
        )
        instructions = (
            f"{system_text}\n\n"
            "Return exactly one JSON object matching the following schema. "
            "Do not include markdown fences or explanatory text.\n"
            f"{json.dumps(self.schema.model_json_schema(), ensure_ascii=False)}"
        )
        raw = codex_response(prompt, model=self.model, instructions=instructions).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].removesuffix("```").strip()
        try:
            return self.schema.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            raise RefineOutputError("Codex response did not match the notice schema") from exc

    def batch(self, prompts: list, *, config=None, return_exceptions: bool = False) -> list:
        results = []
        for messages in prompts:
            try:
                results.append(self.invoke(messages))
            except Exception as exc:
                if not return_exceptions:
                    raise
                results.append(exc)
        return results


def _text_llm(settings: dict):
    provider = settings["provider"]
    model = settings["model"] or LLM_MODEL
    api_key = settings["api_key"]
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
        client_class = _OllamaChatOpenAI if provider == "ollama" else ChatOpenAI
        return client_class(
            model=model,
            base_url=settings["base_url"] or default_url,
            api_key=api_key or "local",
            # 구조화 추출은 재현성과 사실 보존이 중요하므로 기본값을 최저로 둔다.
            temperature=_env_float("LOCAL_LLM_TEMPERATURE", 0.0),
            # Gemma 계열 chat template가 지원하는 내부 추론은 공지 구조화에는
            # 불필요하다. LM Studio가 모델 기본값으로 thinking을 켜더라도
            # 명시적으로 비활성화해 수집 지연과 불필요한 token 소비를 막는다.
            extra_body=_local_extra_body(provider),
            # OpenAI-compatible local models do not always emit a stop token
            # reliably for OCR/structured-output requests. Without a limit,
            # one malformed response can occupy LM Studio until its full
            # context window is exhausted and stall the entire ingest worker.
            max_tokens=_env_int("LOCAL_LLM_MAX_TOKENS", 2048),
            timeout=LOCAL_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )

    raise ValueError(f"지원하지 않는 provider: {provider}")


def _active_embedding() -> dict:
    return load_settings()["embedding"]


@lru_cache(maxsize=12)
def _embedding_client(provider: str, model: str, base_url: str, api_key: str, dimension: int):
    if provider == "google":
        return GoogleGenerativeAIEmbeddings(
            model=model,
            output_dimensionality=dimension,
            google_api_key=api_key or GOOGLE_API_KEY,
        )

    if provider == "openai":
        return OpenAIEmbeddings(
            model=model,
            api_key=api_key or OPENAI_API_KEY,
            dimensions=dimension,
        )

    if provider in {"ollama", "lmstudio", "local"}:
        default_url = (
            "http://127.0.0.1:11434/v1"
            if provider in {"ollama", "local"}
            else "http://127.0.0.1:1234/v1"
        )
        return OpenAIEmbeddings(
            model=model,
            base_url=base_url or default_url,
            api_key=api_key or "local",
            dimensions=dimension,
            check_embedding_ctx_length=False,
        )

    raise ValueError(f"지원하지 않는 provider: {provider}")


def get_embeddings(settings: dict | None = None):
    value = settings or _active_embedding()
    return _embedding_client(
        str(value.get("provider") or EMBEDDING_PROVIDER).lower(),
        str(value.get("model") or EMBEDDING_MODEL),
        str(value.get("base_url") or OPENAI_COMPAT_BASE_URL),
        str(value.get("api_key") or ""),
        int(value.get("dimension") or EMBEDDING_DIM),
    )
