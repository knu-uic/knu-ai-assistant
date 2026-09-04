import re
from typing import Any
from model import get_embeddings


# context window 기반 동적 chunk 크기.
# 너무 작은 chunk는 retrieval precision은 좋아도 context fragmentation이 심해진다.
CHUNK_SIZE = 280
CHUNK_OVERLAP = 80


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


def _figure_context_prefix(content: str, start: int, chunk: str) -> str:
    """그림 설명이 청킹 경계에서 번호와 갈라지면 해당 번호를 복원한다."""
    marker_pattern = r"\[(?:본문\s+)?그림\s+\d+\]"
    if "[그림 설명]" not in chunk or re.search(marker_pattern, chunk):
        return ""
    matches = list(re.finditer(marker_pattern, content[:start]))
    if not matches:
        return ""
    marker = matches[-1]
    # 다른 문단의 오래된 그림 번호가 잘못 전파되지 않게 경계 근처만 복원한다.
    if start - marker.start() > 700:
        return ""
    return marker.group(0) + "\n"


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


def chunk_text(content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """줄 경계와 표 문맥을 고려해 텍스트를 청킹."""
    if not content:
        return []

    content = content.strip()

    if not content:
        return []
    chunks: list[str] = []
    start = 0
    n = len(content)
    while start < n:
        end = _choose_chunk_end(content, start, start + chunk_size, n, chunk_size)
        chunk = content[start:end]
        prefixes = (
            _table_context_prefix(content, start, min(end, n), chunk)
            + _figure_context_prefix(content, start, chunk)
        )
        chunks.append(prefixes + chunk if prefixes else chunk)
        if end >= n:
            break
        start = _choose_chunk_start(content, max(0, end - overlap), n, overlap)
    return chunks


def embed_chunks(content: str) -> list[tuple[int, str, list[float]]]:
    """content를 청크로 쪼개고 각 청크 임베딩까지 계산해서 반환.

    반환: [(chunk_idx, chunk_content, embedding_vector), ...]
    """
    chunks = chunk_text(content)
    if not chunks:
        return []
    embedder = get_embeddings()
    vectors = embedder.embed_documents(chunks)

    return [
        (i, c, v)
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]


def embed_document_chunks(
    title: str,
    body_content: str,
    attachment_contents: list[dict] | None = None,
) -> list[tuple[int, str, list[float], str, str | None]]:
    """문서 전체를 body/attachment 단위로 분리 청킹 후 임베딩.

    반환:
    [
        (
            chunk_idx,
            chunk_text,
            embedding,
            chunk_type,
            attachment_name,
        )
    ]
    """

    attachment_contents = attachment_contents or []

    title = (title or "").strip()
    body_content = (body_content or "").strip()

    chunk_inputs: list[dict[str, Any]] = []

    # body chunk
    if body_content.strip():
        chunk_inputs.append({
            "chunk_type": "body",
            "attachment_name": None,
            "text": body_content,
        })

    # attachment chunk
    for att in attachment_contents:
        text = (att.get("text") or "").strip()

        if not text:
            continue

        figure_match = re.search(r"\[(?:본문\s+)?그림\s+\d+\]", text)
        is_figure = att.get("type") in {
            "attachment_hwp_figure", "attachment_figure", "body_figure",
        }
        chunk_inputs.append({
            "chunk_type": "body_figure" if att.get("type") == "body_figure" else "attachment",
            "attachment_name": att.get("name"),
            "text": text,
            "figure_marker": (
                figure_match.group(0)
                if is_figure and figure_match
                else None
            ),
        })

    if not chunk_inputs:
        return []

    embedder = get_embeddings()

    results: list[tuple[int, str, list[float], str, str | None]] = []

    chunk_idx = 0

    for item in chunk_inputs:
        chunk_type = item["chunk_type"]
        attachment_name = item["attachment_name"]
        text = item["text"]
        figure_marker = item.get("figure_marker")

        # 꼬리표를 합치지 않은 순수한 본문 텍스트 기준 분할
        chunks = chunk_text(text)
        if figure_marker:
            chunks = [
                chunk if figure_marker in chunk else f"{figure_marker}\n{chunk}"
                for chunk in chunks
            ]

        if not chunks:
            continue

        # 모든 쪼개진 개별 청크의 맨 앞에 공지 제목 꼬리표 부착
        if title:
            enriched_chunks = [f"[공지 제목: {title}]\n{c}" for c in chunks]
        else:
            enriched_chunks = chunks

        vectors = embedder.embed_documents(enriched_chunks)

        for chunk_text_value, vector in zip(enriched_chunks, vectors):
            results.append(
                (
                    chunk_idx,
                    chunk_text_value,
                    vector,
                    chunk_type,
                    attachment_name,
                )
            )

            chunk_idx += 1

    return results


def embed_query(query: str) -> list[float]:
    """검색 쿼리 임베딩."""
    return get_embeddings().embed_query(
        (query or "").strip()
    )
