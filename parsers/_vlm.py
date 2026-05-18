"""VLM 공용 호출 유틸. document_parser·curriculum_parser 양쪽에서 import.

설계:
- `image_to_text(bytes, mime, prompt, model)` 단일 진입점. 호출자가 prompt + model 지정.
- `_client(model)` 은 모델별 1 인스턴스 lru_cache (공지용 VLM_MODEL과 커리큘럼용
  CURRICULUM_VLM_MODEL 등 여러 모델 공존 가능).
- temperature=0 고정 — OCR/정형 추출은 일관성이 생명.
"""

import base64
from functools import lru_cache

from langchain_core.messages import HumanMessage

from config import GOOGLE_API_KEY, LLM_PROVIDER, OPENAI_API_KEY, VLM_MODEL


@lru_cache(maxsize=4)
def _client(model: str):
    """모델별 LangChain Chat 클라이언트 1개씩 캐시. provider 토글 따름."""
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=OPENAI_API_KEY, temperature=0)
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, google_api_key=GOOGLE_API_KEY, temperature=0)


def _image_block(provider: str, data_url: str) -> dict:
    """provider별 langchain image block 포맷.

    - OpenAI Vision: image_url 은 객체 {"url": "..."}
    - Gemini (langchain-google-genai): image_url 은 문자열 "data:..." (편의 단축형)
    """
    if provider == "openai":
        return {"type": "image_url", "image_url": {"url": data_url}}
    return {"type": "image_url", "image_url": data_url}


def image_to_text(image_bytes: bytes, mime: str, prompt: str, model: str = VLM_MODEL) -> str:
    """이미지 bytes를 VLM에 던져 텍스트로 받는다. prompt와 model을 호출자가 지정."""
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    msg = HumanMessage(content=[
        {"type": "text", "text": prompt},
        _image_block(LLM_PROVIDER, data_url),
    ])
    response = _client(model).invoke([msg])
    # 가끔 content가 list-of-blocks로 올 때가 있어 방어적 문자열화
    return response.content if isinstance(response.content, str) else str(response.content)
