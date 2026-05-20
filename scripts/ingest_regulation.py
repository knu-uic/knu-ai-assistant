"""data/regulations/<key>.hwpx → 조항 단위 청킹 → document_regulation 적재.

용도: 학칙·학사관리규정 등 방대한 규정 문서.
정책: VLM 절대 금지 (1000+ 페이지 분량 → 비용·시간 폭주).
      .hwpx 는 hwpx_bytes_to_text (ZIP+XML 순수 파이썬) 직접 호출.
      다른 확장자(.pdf 등)는 본 스크립트에서 명시적 skip — 별도 처리 필요.
LLM: refine 안 부름 (pre_refined 패턴). embed_query 만 호출.

운영 절차:
1. 학교 게시판에서 .hwpx 원본 다운로드.
2. data/regulations/<key>.hwpx 로 저장.
3. REGULATION_REGISTRY 에 동일 key 항목 추가 (title + page_url).
4. docker compose exec app python scripts/ingest_regulation.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db import insert_chunks, insert_document, upsert_source
from embed import embed_query
from parsers.document_parser import hwpx_bytes_to_text


DATA_DIR = _ROOT / "data" / "regulations"

REGULATION_REGISTRY: dict[str, dict] = {
    "academic_rule": {
        "title": "공주대학교 학칙",
        # DB url 칼럼 + 챗봇 답변 출처 링크에 들어갈 영구 게시판 URL (학생 다운로드용).
        "page_url": "https://kongju.ac.kr/KNU/17151/subview.do",
    },
    # 추가 규정은 여기에 한 줄씩 더한다. 파일은 data/regulations/<key>.hwpx 로 둔다.
}

_SOURCE_CODE = "regulation"
_CATEGORY = "규정/학칙"
_ARTICLE_RE = re.compile(r"^\s*제\s*(\d+(?:-\d+)?)\s*조", re.MULTILINE)
_MIN_CHUNK = 200
_MAX_CHUNK = 1500
_SUPPORTED_EXT = {".hwpx"}


def _fallback_split(content: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=100,
    ).split_text(content)


def _split_articles(content: str) -> list[str]:
    """`제N조` 라인을 경계로 분할. 짧으면 병합, 너무 길면 RecursiveSplitter 폴백."""
    starts = [m.start() for m in _ARTICLE_RE.finditer(content)]
    if not starts:
        return _fallback_split(content)

    # 첫 조항 앞 prelude(서문·목차)는 길이 미달이면 폐기 — 통상 헤더성 텍스트라 검색 가치 낮음.
    prelude = content[:starts[0]].strip()
    articles: list[str] = [prelude] if len(prelude) >= _MIN_CHUNK else []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(content)
        articles.append(content[s:e].strip())

    # min 가드: 직전 청크가 짧으면 현재를 그 뒤에 붙임.
    merged: list[str] = []
    for art in articles:
        if not art:
            continue
        if merged and len(merged[-1]) < _MIN_CHUNK:
            merged[-1] = merged[-1] + "\n" + art
        else:
            merged.append(art)

    # max 가드: 너무 긴 조항(별표 등)은 RecursiveSplitter 폴백.
    result: list[str] = []
    for art in merged:
        if len(art) <= _MAX_CHUNK:
            result.append(art)
        else:
            result.extend(_fallback_split(art))
    return result


def _extract_text(path: Path) -> str:
    """확장자별 텍스트 추출. VLM 호출 0건 보장."""
    ext = path.suffix.lower()
    if ext == ".hwpx":
        return hwpx_bytes_to_text(path.read_bytes())
    raise ValueError(f"unsupported extension {ext}")


def _embed_with_prefix(title: str, articles: list[str]) -> list[tuple[int, str, list[float]]]:
    """청크 앞에 `[규정: <title>]` 꼬리표 + per-chunk embed_query (Gemini batch 버그 회피)."""
    chunks: list[tuple[int, str, list[float]]] = []
    for idx, art in enumerate(articles):
        enriched = f"[규정: {title}]\n{art}"
        vec = embed_query(enriched)
        chunks.append((idx, enriched, vec))
    return chunks


def ingest_one(key: str, meta: dict) -> int:
    title = meta["title"]
    page_url = meta["page_url"]

    matched = [p for p in DATA_DIR.glob(f"{key}.*") if p.suffix.lower() in _SUPPORTED_EXT]
    if not matched:
        all_matched = list(DATA_DIR.glob(f"{key}.*"))
        if all_matched:
            print(f"[skip] {key}: 지원 안 함 확장자 {[p.suffix for p in all_matched]} (.hwpx 만 지원)")
        else:
            print(f"[skip] {key}: 파일 없음 ({DATA_DIR}/{key}.*)")
        return 0

    path = matched[0]
    print(f"=== {key}: {title} ({path.name}) ===")
    text = _extract_text(path).strip()
    if not text:
        print(f"[skip] {key}: 본문 추출 결과 비어있음")
        return 0

    articles = _split_articles(text)
    if not articles:
        print(f"[skip] {key}: 조항 분할 결과 0")
        return 0

    source_id = upsert_source(
        code=_SOURCE_CODE,
        name="공주대 학교 규정",
        kind="academic",
        department=None,
    )
    document_id = insert_document(
        source_id=source_id,
        url=page_url,
        title=title,
        content=text,
        start_date=None,
        end_date=None,
        category=_CATEGORY,
        target=["전체"],
        keywords=["규정", "학칙", "조항"],
        posted_at=None,
    )
    chunks = _embed_with_prefix(title, articles)
    insert_chunks(_CATEGORY, document_id, chunks)
    print(f"[ok] {key}: {len(articles)}개 chunk 적재 (document_id={document_id})")
    return len(articles)


def main() -> None:
    if not DATA_DIR.exists():
        raise SystemExit(f"{DATA_DIR} 폴더 없음. 먼저 .hwpx 파일을 드롭하세요.")
    total = 0
    for key, meta in REGULATION_REGISTRY.items():
        total += ingest_one(key, meta)
    print(f"=== 완료. 총 chunk {total}개 ===")


if __name__ == "__main__":
    main()
