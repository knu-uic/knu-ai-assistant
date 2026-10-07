"""KNU MCP 도구가 공유하는 검색·재순위화 경로. 답변 LLM을 호출하지 않는다."""
from __future__ import annotations

from typing import Any

from langsmith import traceable

from api.figures import related_figures
from config import RERANK_CANDIDATES, RERANK_TOP_N, SUPPORT_DOC_TOP_N
from db import get_document_content, search_chunks
from embedding.embed import embed_query
from retrieval.rerank import rerank_scores

EVIDENCE_TOP_K = RERANK_TOP_N


@traceable(run_type="retriever", name="vector_search")
def _vector_search(q_vec, major, categories, *, time_scope="current", year=None,
                   content_ids=None, content_type=None):
    return search_chunks(
        q_vec, major=major, categories=categories, limit=RERANK_CANDIDATES,
        time_scope=time_scope, year=year, content_ids=content_ids,
        content_type=content_type,
    )


@traceable(name="rerank")
def _rerank(query: str, rows):
    try:
        scores = rerank_scores(query, [row[2] for row in rows])
    except Exception as error:
        print(f"reranker unavailable; using vector scores: {error}")
        scores = [float(row[3] or 0.0) for row in rows]
    return sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)


def _dedup_text(base: str, remove: list[str]) -> str:
    result = base
    for text in remove:
        text = (text or "").strip()
        if text:
            result = result.replace(text, "")
    return result.strip()


@traceable(run_type="retriever", name="search_chunks_reranked")
def _retrieve_with_rerank(
    query: str,
    major: str | None,
    categories: list[str] | None,
    *,
    time_scope: str = "current",
    year: int | None = None,
    content_ids: list[int] | None = None,
    content_type: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    q_vec = embed_query(query)
    rows = _vector_search(
        q_vec, major, categories, time_scope=time_scope, year=year,
        content_ids=content_ids, content_type=content_type,
    )
    if not rows:
        return [], []

    ranked = _rerank(query, rows)
    evidence_ranked = ranked[:EVIDENCE_TOP_K]
    evidence_chunks = [
        {
            "url": row[0], "title": row[1], "chunk": row[2],
            "score": score, "vector_score": row[3], "rerank_score": score,
            "posted_at": row[4], "start_date": row[5], "end_date": row[6],
            "category": row[7], "source_name": row[11], "source_kind": row[12],
            "source_department": row[13],
            "summary": row[14] if len(row) > 14 else None,
            "related_images": related_figures(row[17] if len(row) > 17 else [], row[2]),
        }
        for row, score in evidence_ranked
    ]

    doc_best = {}
    for row, score in ranked:
        key = f"{row[7]}::{row[0]}"
        previous = doc_best.get(key)
        if previous is None or score > previous[1]:
            doc_best[key] = (row, score)
    top_docs = sorted(doc_best.values(), key=lambda pair: pair[1], reverse=True)[:SUPPORT_DOC_TOP_N]
    evidence_by_url: dict[str, list[str]] = {}
    for evidence in evidence_chunks:
        evidence_by_url.setdefault(evidence["url"], []).append(evidence["chunk"])

    contexts = []
    for row, score in top_docs:
        full = get_document_content(row[0], row[7], row[12]) or row[2]
        deduped_full = _dedup_text(full, evidence_by_url.get(row[0], []))
        contexts.append({
            "url": row[0], "title": row[1],
            "body_content": row[15] if len(row) > 15 else deduped_full,
            "attachment_names": row[16] if len(row) > 16 else [],
            "related_images": related_figures(row[17] if len(row) > 17 else [], row[2]),
            "snippet": deduped_full, "score": score,
            "vector_score": row[3], "rerank_score": score, "matched_chunk": row[2],
            "summary": row[14] if len(row) > 14 else None,
            "posted_at": row[4], "start_date": row[5], "end_date": row[6],
            "category": row[7], "source_name": row[11], "source_kind": row[12],
            "source_department": row[13],
        })
    return contexts, evidence_chunks


def retrieve_mcp_evidence(
    question: str,
    department: str | None = None,
    category_override: str | None = None,
    time_scope: str = "current",
    year: int | None = None,
    content_ids: list[int] | None = None,
    content_type: str | None = None,
) -> dict:
    """검색 도구가 선택한 필터를 그대로 적용하며 별도 LLM 분류는 하지 않는다."""
    query = question.strip()
    categories = [category_override] if category_override else []
    contexts, evidence_chunks = _retrieve_with_rerank(
        query, department, categories or None, time_scope=time_scope,
        year=year, content_ids=content_ids, content_type=content_type,
    )
    return {
        "query_mode": "deep", "original_query": question,
        "expanded_query": query, "categories": categories,
        "department": department, "time_scope": time_scope, "year": year,
        "notice_ids": list(content_ids or []), "source_kind": content_type,
        "routing_fallback": False, "contexts": contexts,
        "evidence_chunks": evidence_chunks,
    }
