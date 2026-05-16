from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv
import os


def get_llm():
    load_dotenv()
    VLM_PROVIDER = "lmstudio"  # "google" or "lmstudio"

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
    EMBEDDING_PROVIDER = "lmstudio"  # "google" or "lmstudio"
    
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