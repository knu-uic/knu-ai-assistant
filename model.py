from functools import lru_cache

from config import LLM_PROVIDER, LLM_MODEL, OPENAI_API_KEY, GOOGLE_API_KEY


@lru_cache(maxsize=1)
def get_model():
    """provider 토글에 따라 OpenAI/Gemini Chat 모델 클라이언트를 돌려준다."""
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=LLM_MODEL, api_key=OPENAI_API_KEY)
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=LLM_MODEL, google_api_key=GOOGLE_API_KEY)
