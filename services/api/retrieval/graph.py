"""LangGraph RAG 파이프라인 조립 모듈."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langsmith import traceable
from pydantic import BaseModel, Field
from api.figures import collect_related_figures, related_figures

from config import (
    BROAD_DOC_TOP_N,
    BROAD_RERANK_CANDIDATES,
    ENABLE_VERIFIER,
    RERANK_CANDIDATES,
    RERANK_TOP_N,
    SUPPORT_DOC_TOP_N,
)
from db import get_document_content, search_chunks
from embedding.embed import embed_query
from model import get_llm
from retrieval.context_packing import _format_broad_context, pack_contexts
from retrieval.prompts import (
    ANSWERER_SYSTEM,
    BROAD_ANSWERER_SYSTEM,
    ROUTER_SYSTEM,
    SMALLTALK_SYSTEM,
    VERIFIER_SYSTEM,
)
from retrieval.rerank import rerank_scores


Category = Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"]


class RouteDecision(BaseModel):
    query_mode: Literal["precise", "broad", "smalltalk"] = Field(
        description=(
            "precise=특정 공지 1건의 구체 사실을 묻는 질문. "
            "broad=여러 공지를 한눈에 훑는 집계/목록형 질문. "
            "smalltalk=검색이 불필요한 인사·잡담·감사·챗봇 자체 질문. 애매하면 precise."
        )
    )
    categories: List[Category] = Field(
        description="검색할 카테고리 리스트. 모호하면 여러 개, 명확히 무관하면 1개만."
    )
    expanded_query: str = Field(
        description=(
            "공지 제목의 격식체와 도메인 유의어를 반영해 임베딩 검색용으로 다듬은 쿼리. "
            "원문의 핵심 의미는 유지하고 '알려줘/조회해' 같은 서술어는 제거한다."
        )
    )
    rationale: str = Field(description="분류·확장 결정 이유 한 줄")


class VerificationResult(BaseModel):
    grounded: bool = Field(description="답변의 핵심 사실이 컨텍스트에 명시되어 있으면 True")
    fidelity: float = Field(description="0.0(전부 환각)~1.0(전부 근거 있음)")
    note: str = Field(description="할루시네이션이 의심되는 부분 또는 OK 사유")


class ChatState(TypedDict, total=False):
    question: str
    query_mode: str
    major: str | None
    categories: List[Category]
    expanded_query: str
    route_rationale: str
    contexts: List[Dict[str, Any]]
    evidence_chunks: List[Dict[str, Any]]
    answer: str
    grounded: bool
    fidelity: float
    verifier_note: str
    related_images: List[Dict[str, Any]]


def router_node(state: ChatState) -> dict:
    model = get_llm().with_structured_output(RouteDecision)
    decision = model.invoke(
        [SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=state["question"])]
    )
    return {
        "query_mode": decision.query_mode,  # type: ignore[union-attr]
        "categories": list(decision.categories),  # type: ignore[union-attr]
        "expanded_query": decision.expanded_query,  # type: ignore[union-attr]
        "route_rationale": decision.rationale,  # type: ignore[union-attr]
    }


@traceable(run_type="retriever", name="search_chunks")
def _retrieve(
    query: str,
    major: str | None,
    categories: List[str] | None,
) -> List[Dict[str, Any]]:
    q_vec = embed_query(query)
    rows = search_chunks(q_vec, major=major, categories=categories)
    return [
        {
            "url": r[0],
            "title": r[1],
            "snippet": r[2],
            "score": r[3],
            "posted_at": r[4],
            "start_date": r[5],
            "end_date": r[6],
            "summary": r[14] if len(r) > 14 else None,
            "related_images": related_figures(r[17] if len(r) > 17 else [], r[2]),
        }
        for r in (rows or [])
    ]


EVIDENCE_TOP_K = RERANK_TOP_N


@traceable(run_type="retriever", name="vector_search")
def _vector_search(
    q_vec,
    major,
    categories,
    *,
    time_scope: str = "current",
    year: int | None = None,
    notice_ids: list[int] | None = None,
):
    return search_chunks(
        q_vec,
        major=major,
        categories=categories,
        limit=RERANK_CANDIDATES,
        time_scope=time_scope,
        year=year,
        notice_ids=notice_ids,
    )


@traceable(name="rerank")
def _rerank(query: str, rows):
    try:
        scores = rerank_scores(query, [r[2] for r in rows])
    except Exception as error:
        # MCP/search must remain usable when the optional local CrossEncoder or
        # hosted reranker is unavailable. pgvector distance is already present
        # at index 3 and is a safe, deterministic fallback ranking signal.
        print(f"reranker unavailable; using vector scores: {error}")
        scores = [float(r[3] or 0.0) for r in rows]
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
    categories: List[str] | None,
    *,
    time_scope: str = "current",
    year: int | None = None,
    notice_ids: list[int] | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    q_vec = embed_query(query)
    rows = _vector_search(
        q_vec,
        major,
        categories,
        time_scope=time_scope,
        year=year,
        notice_ids=notice_ids,
    )
    if not rows:
        return [], []

    ranked = _rerank(query, rows)
    evidence_ranked = ranked[:EVIDENCE_TOP_K]
    evidence_chunks: List[Dict[str, Any]] = [
        {
            "url": r[0],
            "title": r[1],
            "chunk": r[2],
            "score": s,
            "vector_score": r[3],
            "rerank_score": s,
            "posted_at": r[4],
            "start_date": r[5],
            "end_date": r[6],
            "category": r[7],
            "source_name": r[11],
            "source_department": r[13],
            "summary": r[14] if len(r) > 14 else None,
            "related_images": related_figures(r[17] if len(r) > 17 else [], r[2]),
        }
        for r, s in evidence_ranked
    ]

    doc_best: dict[str, tuple[Any, float]] = {}
    for r, s in ranked:
        key = f"{r[7]}::{r[0]}"
        prev = doc_best.get(key)
        if prev is None or s > prev[1]:
            doc_best[key] = (r, s)

    top_docs = sorted(doc_best.values(), key=lambda pair: pair[1], reverse=True)[
        :SUPPORT_DOC_TOP_N
    ]

    evidence_by_url: dict[str, list[str]] = {}
    for ev in evidence_chunks:
        evidence_by_url.setdefault(ev["url"], []).append(ev["chunk"])

    contexts: List[Dict[str, Any]] = []
    for r, s in top_docs:
        full = get_document_content(r[0], r[7]) or r[2]
        deduped_full = _dedup_text(full, evidence_by_url.get(r[0], []))
        contexts.append(
            {
                "url": r[0],
                "title": r[1],
                "body_content": r[15] if len(r) > 15 else deduped_full,
                "attachment_names": r[16] if len(r) > 16 else [],
                "related_images": related_figures(r[17] if len(r) > 17 else [], r[2]),
                "snippet": deduped_full,
                "score": s,
                "vector_score": r[3],
                "rerank_score": s,
                "matched_chunk": r[2],
                "summary": r[14] if len(r) > 14 else None,
                "posted_at": r[4],
                "start_date": r[5],
                "end_date": r[6],
                "category": r[7],
                "source_name": r[11],
                "source_department": r[13],
            }
        )

    return contexts, evidence_chunks


def retriever_node(state: ChatState) -> dict:
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None
    contexts, evidence_chunks = _retrieve_with_rerank(
        query,
        state.get("major"),
        categories,
    )
    return {
        "contexts": contexts,
        "evidence_chunks": evidence_chunks,
        "related_images": collect_related_figures(
            *(context.get("related_images") or [] for context in contexts),
            *(evidence.get("related_images") or [] for evidence in evidence_chunks),
        ),
    }


@traceable(run_type="retriever", name="search_chunks_broad")
def _retrieve_broad(
    query: str,
    major: str | None,
    categories: List[str] | None,
) -> List[Dict[str, Any]]:
    q_vec = embed_query(query)
    rows = search_chunks(
        q_vec,
        major=major,
        categories=categories,
        limit=BROAD_RERANK_CANDIDATES,
        distinct_by_doc=True,
    )
    if not rows:
        return []

    ranked = _rerank(query, rows)
    top = ranked[:BROAD_DOC_TOP_N]
    return [
        {
            "url": r[0],
            "title": r[1],
            "matched_chunk": r[2],
            "summary": r[14] if len(r) > 14 else None,
            "posted_at": r[4],
            "start_date": r[5],
            "end_date": r[6],
            "category": r[7],
            "source_name": r[11],
            "source_department": r[13],
            "score": s,
            "vector_score": r[3],
            "rerank_score": s,
            "related_images": related_figures(r[17] if len(r) > 17 else [], r[2]),
        }
        for r, s in top
    ]


def broad_retriever_node(state: ChatState) -> dict:
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None
    contexts = _retrieve_broad(query, state.get("major"), categories)
    return {
        "contexts": contexts,
        "evidence_chunks": [],
        "related_images": collect_related_figures(
            *(context.get("related_images") or [] for context in contexts)
        ),
    }


def retrieve_mcp_evidence(
    question: str,
    department: str | None = None,
    category_override: str | None = None,
    time_scope: str = "current",
    year: int | None = None,
    notice_ids: list[int] | None = None,
) -> dict:
    """Retrieve Deep MCP evidence without invoking a second LLM.

    The upstream Codmes model has already chosen this tool and supplied the
    structured filters. KNU does not classify the question again.
    """
    query = question.strip()
    categories = [category_override] if category_override else []
    contexts, evidence_chunks = _retrieve_with_rerank(
        query,
        department,
        categories or None,
        time_scope=time_scope,
        year=year,
        notice_ids=notice_ids,
    )

    return {
        "query_mode": "deep",
        "original_query": question,
        "expanded_query": query,
        "categories": categories,
        "department": department,
        "time_scope": time_scope,
        "year": year,
        "notice_ids": list(notice_ids or []),
        "routing_fallback": False,
        "contexts": contexts,
        "evidence_chunks": evidence_chunks,
    }


def answerer_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    if not contexts:
        return {"answer": "관련 공지를 찾지 못했습니다."}

    context_text = pack_contexts(
        contexts,
        state.get("evidence_chunks") or [],
    )
    today = date.today().isoformat()
    resp = get_llm().invoke(
        [
            SystemMessage(content=ANSWERER_SYSTEM),
            HumanMessage(
                content=(
                    f"# 오늘 날짜\n{today}\n\n"
                    f"# 사용자 질문\n{state['question']}\n\n"
                    f"# 컨텍스트\n{context_text}"
                )
            ),
        ]
    )
    answer = resp.content if hasattr(resp, "content") else str(resp)
    return {"answer": answer}


def broad_answerer_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    if not contexts:
        return {"answer": "관련 공지를 찾지 못했습니다."}

    context_text = _format_broad_context(contexts, budget=6000)
    today = date.today().isoformat()
    resp = get_llm().invoke(
        [
            SystemMessage(content=BROAD_ANSWERER_SYSTEM),
            HumanMessage(
                content=(
                    f"# 오늘 날짜\n{today}\n\n"
                    f"# 사용자 질문\n{state['question']}\n\n"
                    f"# 컨텍스트\n{context_text}"
                )
            ),
        ]
    )
    answer = resp.content if hasattr(resp, "content") else str(resp)
    return {"answer": answer}


def verifier_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    context_text = pack_contexts(
        contexts,
        state.get("evidence_chunks") or [],
    )
    today = date.today().isoformat()

    result = get_llm().with_structured_output(VerificationResult).invoke(
        [
            SystemMessage(content=VERIFIER_SYSTEM),
            HumanMessage(
                content=(
                    f"# 오늘 날짜\n{today}\n\n"
                    f"# 답변\n{state.get('answer', '')}\n\n"
                    f"# 컨텍스트\n{context_text}"
                )
            ),
        ]
    )
    return {
        "grounded": result.grounded,  # type: ignore[union-attr]
        "fidelity": result.fidelity,  # type: ignore[union-attr]
        "verifier_note": result.note,  # type: ignore[union-attr]
    }


def smalltalk_node(state: ChatState) -> dict:
    # 검색 없이 바로 답하는 가벼운 응답(인사·잡담·감사·자기소개).
    resp = get_llm().invoke(
        [
            SystemMessage(content=SMALLTALK_SYSTEM),
            HumanMessage(content=state["question"]),
        ]
    )
    return {"answer": resp.content, "contexts": [], "evidence_chunks": []}


def _route_by_mode(state: ChatState) -> str:
    mode = state.get("query_mode")
    if mode == "smalltalk":
        return "smalltalk"
    return "broad" if mode == "broad" else "precise"


def build_graph():
    g = StateGraph(ChatState)
    g.add_node("router", router_node)
    g.add_node("retriever", retriever_node)
    g.add_node("answerer", answerer_node)
    g.add_node("broad_retriever", broad_retriever_node)
    g.add_node("broad_answerer", broad_answerer_node)
    g.add_node("smalltalk", smalltalk_node)

    g.set_entry_point("router")
    g.add_conditional_edges(
        "router",
        _route_by_mode,
        {"precise": "retriever", "broad": "broad_retriever", "smalltalk": "smalltalk"},
    )
    g.add_edge("retriever", "answerer")
    g.add_edge("broad_retriever", "broad_answerer")
    g.add_edge("broad_answerer", END)
    g.add_edge("smalltalk", END)

    if ENABLE_VERIFIER:
        g.add_node("verifier", verifier_node)
        g.add_edge("answerer", "verifier")
        g.add_edge("verifier", END)
    else:
        g.add_edge("answerer", END)

    return g.compile()


GRAPH = build_graph()
