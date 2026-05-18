from typing import List, Tuple
from model import get_embeddings



EMBEDDING_DIM = 768  # HNSW 한계(2000) 회피 + 비용/속도 우선. MTEB는 3072 대비 ~0.2점 손실로 무시 가능.
CHUNK_SIZE = 800 # 청크사이즈란 한번에 처리할 텍스트의 길이를 의미합니다. 이 값을 늘리면 메모리 사용량이 증가하지만, 처리 속도는 빨라집니다. 반대로 줄이면 메모리 사용량은 감소하지만, 처리 속도는 느려집니다.
CHUNK_OVERLAP = 100  #청크오버랩이란 두 청크 사이의 겹치는 부분을 의미합니다. 이것은 청크 사이의 유사성을 높이는 데 도움이 됩니다.


def chunk_text(content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """800자 슬라이딩 윈도우 + 100자 overlap. 한국어 공지 기준."""
    if not content:
        return []
    chunks: List[str] = []
    start = 0
    n = len(content)
    while start < n:
        end = start + chunk_size
        chunks.append(content[start:end])
        if end >= n:
            break
        start = end - overlap
    return chunks


def embed_chunks(content: str) -> List[Tuple[int, str, List[float]]]:
    """content를 청크로 쪼개고 각 청크 임베딩까지 계산해서 반환.

    반환: [(chunk_idx, chunk_content, embedding_vector), ...]
    """
    chunks = chunk_text(content)
    if not chunks:
        return []
    embedder = get_embeddings()
    vectors = embedder.embed_documents(chunks)
    return [(i, c, v) for i, (c, v) in enumerate(zip(chunks, vectors))]


def embed_query(query: str) -> List[float]:
    """검색 쿼리 임베딩."""
    return get_embeddings().embed_query(query)
