from typing import List, Tuple
from model import get_embeddings


CHUNK_SIZE = 400 
CHUNK_OVERLAP = 100 


def _line_at(content: str, pos: int) -> str:
    line_start = content.rfind("\n", 0, pos)
    line_end = content.find("\n", pos)
    if line_end == -1:
        line_end = len(content)
    return content[line_start + 1:line_end].strip()


def _last_marker_line(content: str, marker: str, before: int) -> tuple[int, str]:
    pos = content.rfind(marker, 0, before)
    if pos == -1:
        return -1, ""
    return pos, _line_at(content, pos)


def _table_context_prefix(content: str, start: int, end: int, chunk: str) -> str:
    """청킹 경계로 잘린 엑셀 표 조각 앞에 현재 Sheet/헤더를 보강."""
    table_header_marker = "[표 헤더]"
    table_row_marker = "[행]"
    sheet_marker = "[Sheet:"
    sheet_end_marker = "[End Sheet:"
    if table_header_marker in chunk:
        return ""

    header_pos, header_line = _last_marker_line(content, table_header_marker, start)
    if header_pos == -1:
        return ""

    end_pos = content.rfind(sheet_end_marker, 0, start)
    if end_pos > header_pos:
        return ""

    # 지금 chunk가 표 데이터 근처일 때만 보강한다. 문서 뒤쪽 일반 본문에
    # 마지막 표 헤더가 계속 붙는 것을 막기 위한 방어 조건.
    last_row_pos = content.rfind(table_row_marker, 0, end)
    if last_row_pos < header_pos:
        return ""

    _, sheet_line = _last_marker_line(content, sheet_marker, start)
    lines = []
    if sheet_line:
        lines.append(sheet_line)
    lines.append(header_line)
    return "\n".join(lines) + "\n"


def _choose_chunk_end(content: str, start: int, target_end: int, n: int, chunk_size: int) -> int:
    """가능하면 줄 끝에서 청크를 끊어 표 행이 반으로 갈리는 일을 줄인다."""
    if target_end >= n:
        return n

    min_end = start + int(chunk_size * 0.6)
    newline = content.rfind("\n", start + 1, target_end)
    if newline >= min_end:
        return newline + 1
    return target_end


def _choose_chunk_start(content: str, proposed_start: int, n: int, overlap: int) -> int:
    """overlap 지점이 줄 중간이면 다음 줄 시작으로 이동한다."""
    if proposed_start <= 0 or proposed_start >= n:
        return max(0, min(proposed_start, n))
    if content[proposed_start - 1] == "\n":
        return proposed_start
    newline = content.find("\n", proposed_start, min(n, proposed_start + overlap + 1))
    if newline != -1:
        return newline + 1
    return proposed_start


def chunk_text(content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """줄 경계와 표 문맥을 고려해 텍스트를 청킹."""
    if not content:
        return []
    chunks: List[str] = []
    start = 0
    n = len(content)
    while start < n:
        end = _choose_chunk_end(content, start, start + chunk_size, n, chunk_size)
        chunk = content[start:end]
        prefix = _table_context_prefix(content, start, min(end, n), chunk)
        chunks.append(prefix + chunk if prefix else chunk)
        if end >= n:
            break
        start = _choose_chunk_start(content, max(0, end - overlap), n, overlap)
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
