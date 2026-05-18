from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from functools import lru_cache
from dotenv import load_dotenv
import os


# providers
VLM_PROVIDER = "lmstudio"
EMBEDDING_PROVIDER = "lmstudio"

# model names
LLM_MODEL = "gemma-4-e4b"
EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512

def get_llm():
    load_dotenv()
    
    if VLM_PROVIDER == "google":
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-pro-preview",
            google_api_key=(
                os.getenv("GOOGLE_API_KEY")or os.getenv("GEMINI_API_KEY")
            ),
            temperature=0,
        )

    elif VLM_PROVIDER == "lmstudio":
        return ChatOpenAI(
            model="gemma-4-e4b",
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            temperature=0,
        )

    else:

        raise ValueError(

            f"지원하지 않는 provider: {VLM_PROVIDER}"

        )
    


def get_embeddings():
    load_dotenv()
    if EMBEDDING_PROVIDER == "google":

        return GoogleGenerativeAIEmbeddings(

            model="gemini-embedding-2-preview",

            output_dimensionality=768,

        )

    elif EMBEDDING_PROVIDER == "lmstudio":

        return OpenAIEmbeddings(

            model="text-embedding-nomic-embed-text-v1.5",

            base_url="http://localhost:1234/v1",

            api_key="lm-studio",

        )

    else:

        raise ValueError(f"지원하지 않는 provider: {EMBEDDING_PROVIDER}")
    

    
@lru_cache(maxsize=1)
def _get_reranker():
    # import을 lazy 하게: 다른 코드 경로(예: 크롤러)는 torch를 안 쓰는데
    # 모듈 top-level import면 매번 ~수 초 페널티가 붙는다.
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)