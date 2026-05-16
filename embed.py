from functools import lru_cache
from typing import List, Tuple

from config import (
    LLM_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIM,
    CHUNK_SIZE, CHUNK_OVERLAP, OPENAI_API_KEY,
)


@lru_cache(maxsize=1)
def get_embeddings():
    """provider 토글에 따라 OpenAI/Gemini 임베딩 클라이언트를 돌려준다.

    두 provider 모두 결과 차원을 EMBEDDING_DIM(1536)으로 맞춰 HNSW vector 호환.
    """
    if LLM_PROVIDER == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIM,
            api_key=OPENAI_API_KEY,
        )
    # gemini: Matryoshka로 output_dimensionality 1536 truncate.
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        output_dimensionality=EMBEDDING_DIM,
    )


@lru_cache(maxsize=4)
def _get_splitter(chunk_size: int, overlap: int):
    """RecursiveCharacterTextSplitter 싱글톤. lazy import로 cold start 영향 회피."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        # 우선순위: 단락(\n\n) → 줄(\n) → 한국/일본식 문장경계(。) → 영문 문장(. ) → 공백 → 글자.
        # 표/번호리스트가 임의 글자에서 잘리던 단순 sliding window 대비 의미 단위 보존.
        separators=["\n\n", "\n", "。", ". ", " ", ""],
        length_function=len,
    )


def chunk_text(content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """한국어 공지 기준 의미 단위 분할. CHUNK_SIZE 자 상한, CHUNK_OVERLAP 자 overlap."""
    if not content:
        return []
    return _get_splitter(chunk_size, overlap).split_text(content)


def embed_chunks(content: str) -> List[Tuple[int, str, List[float]]]:
    """content를 청크로 쪼개고 각 청크 임베딩까지 계산해서 반환.

    반환: [(chunk_idx, chunk_content, embedding_vector), ...]

    NOTE: gemini-embedding-2-preview의 batch가 silent partial response를 내던
    버그 때문에 per-chunk embed_query로 호출 유지. OpenAI에선 embed_documents도 안전하지만
    provider 교체 시 회귀를 막기 위해 보수적으로 유지.
    """
    chunks = chunk_text(content)
    if not chunks:
        return []
    embedder = get_embeddings()
    vectors = [embedder.embed_query(c) for c in chunks]
    return [(i, c, v) for i, (c, v) in enumerate(zip(chunks, vectors))]


def embed_query(query: str) -> List[float]:
    """검색 쿼리 임베딩."""
    return get_embeddings().embed_query(query)
