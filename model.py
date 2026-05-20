from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from functools import lru_cache
from dotenv import load_dotenv
import os


# providers
VLM_PROVIDER = os.getenv("VLM_PROVIDER", "lmstudio")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "lmstudio")

# model names
LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-e4b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512

def get_llm():
    load_dotenv()
    vlm_provider = os.getenv("VLM_PROVIDER", VLM_PROVIDER)
    llm_model = os.getenv("LLM_MODEL", LLM_MODEL)
    lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL", LMSTUDIO_BASE_URL)
    
    if vlm_provider == "google":
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-pro-preview",
            google_api_key=(
                os.getenv("GOOGLE_API_KEY")or os.getenv("GEMINI_API_KEY")
            ),
            temperature=0,
        )

    elif vlm_provider == "lmstudio":
        return ChatOpenAI(
            model=llm_model,
            base_url=lmstudio_base_url,
            api_key="lm-studio",
            temperature=0,
        )

    else:

        raise ValueError(

            f"지원하지 않는 provider: {vlm_provider}"

        )
    


def get_embeddings():
    load_dotenv()
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", EMBEDDING_PROVIDER)
    embedding_model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL", LMSTUDIO_BASE_URL)
    if embedding_provider == "google":

        return GoogleGenerativeAIEmbeddings(

            model="gemini-embedding-2-preview",

            output_dimensionality=768,

        )

    elif embedding_provider == "lmstudio":

        return OpenAIEmbeddings(

            model=embedding_model,

            base_url=lmstudio_base_url,

            api_key="lm-studio",

            check_embedding_ctx_length=False,

        )

    else:

        raise ValueError(f"지원하지 않는 provider: {embedding_provider}")
    

    
@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)
