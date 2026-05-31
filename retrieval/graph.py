"""LangGraph: 라우터(분류+쿼리확장) → retriever → answerer → verifier 4노드 RAG 파이프라인."""

from datetime import date
from typing import TypedDict, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langsmith import traceable

from db import search_chunks
# === [seungwon/bge-reranker] 시작 ===
from db import get_document_content
from retrieval.rerank import rerank_scores
# === [seungwon/bge-reranker] 끝 ===
from embedding.embed import embed_query
from model import get_llm
from config import (
    RERANK_CANDIDATES,
    RERANK_TOP_N,
    SUPPORT_DOC_TOP_N,
    BROAD_RERANK_CANDIDATES,
    BROAD_DOC_TOP_N,
    ENABLE_VERIFIER,
)


Category = Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"]


class RouteDecision(BaseModel):
    query_mode: Literal["precise", "broad"] = Field(
        description="precise=특정 공지 1건의 구체 사실을 묻는 질문. "
                    "broad=여러 공지를 한눈에 훑는 집계/목록형 질문. 애매하면 precise."
    )
    categories: List[Category] = Field(
        description="검색할 카테고리 리스트. 모호하면 여러 개, 명확히 무관하면 1개만."
    )
    expanded_query: str = Field(
        description="공지 제목의 격식체와 도메인 유의어를 반영해 임베딩 검색용으로 다듬은 쿼리. "
                    "원문의 핵심 의미는 유지하고 '알려줘/조회해' 같은 서술어는 제거한다."
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


ROUTER_SYSTEM = """너는 공주대 학생 질문을 분석해 RAG 파이프라인의 진입점을 결정하는 라우터다.

## 질문 모드 (query_mode)
질문이 둘 중 어느 쪽인지 판단한다.
- precise — 특정 공지 1건의 구체 사실(날짜·금액·자격·장소·절차)을 묻는다.
  예: "국가장학금 신청 언제까지야", "AWS 특강 장소 어디", "복학 신청 어떻게 해"
- broad — 여러 공지를 한눈에 훑고 싶은 집계/목록형이다.
  예: "이번에 올라온 장학 공지 전부 알려줘", "수강 관련 공지 뭐뭐 있어", "이번 달 행사 알려줘"
- 애매하면 precise를 고른다(기본 동작이 안전).

## 카테고리 분류 (categories)
다음 5개 중 질문과 관련 있는 카테고리를 모두 고른다. 
조금이라도 모호하면 여러 개 선택해도 좋다.
1. 장학 — 국가장학금, 교내장학금, 등록금 납부, 학자금 대출 등
2. 수강 — 수강신청, 휴학·복학, 졸업요건, 성적, 교과과정표, 학점 등
3. 취업(진로) — 채용, 인턴, 자격증, 취업특강, 진로상담 등
4. 행사(공모전) — 대회, 해커톤, 동아리, 축제, 세미나 등
5. 일반(기타) — 분실물, 시설, 예비군, 위 4개에 속하지 않는 그 외

## 쿼리 확장 (expanded_query)
공지 제목은 격식체("○○ 모집 안내", "○○ 신청 기간")이고 학생 질문은 구어체라 임베딩 공간에서 거리가 멀다. 다음을 적용해 검색용 쿼리로 다듬는다.

- '알려줘', '조회해', '보여줘', '어떻게 돼' 같은 서술어/조사 제거.
- 핵심 명사 + 도메인 유의어/격식어 2~4개 추가 (과확장 금지).
  - 예: "장학금 알려줘" → "장학금 신청 안내 모집"
  - 예: "졸업학점 얼마야" → "졸업요건 이수학점 졸업기준"
  - 예: "재택근무 규정" → "원격근무 가이드라인 비대면 지침"
- 사용자가 명시한 고유명사(학과, 행사명, 자격증명)는 그대로 유지.
- 너무 많이 늘리면 임베딩 평균이 흐려져 오히려 검색 품질이 떨어진다 — 짧고 정확하게.

## rationale
왜 그 카테고리·확장을 골랐는지 한 줄로.
"""


ANSWERER_SYSTEM = """너는 공주대학교 학생을 돕는 AI 비서다.

반드시 아래 컨텍스트만 근거로 답변하라.

규칙:
- 컨텍스트에 명시된 사실에서 논리적으로 도출되는 결론은 허용한다.
  예: 오늘 날짜와 컨텍스트의 start_date/end_date를 비교해 "현재 접수 중", "이미 마감" 같이 판단하는 것.
- 컨텍스트에 없는 새로운 사실(날짜·금액·자격·연락처 등)은 만들지 마라.
- 컨텍스트에 사용자 질문에 답할 정보가 전혀 없을 때만 "관련 공지를 찾지 못했습니다"라고 답하라.
- 내부 분석 과정, 검토 과정, 추론 과정은 절대 출력하지 마라.
- "사용자 질문 분석", "정보 추출", "논리적 결론", "검토 결과" 같은 중간 단계 설명을 출력하지 마라.
- 반드시 사용자에게 보여줄 최종 답변만 자연스럽게 출력하라.
- 답변 끝에 참고한 공지 제목과 URL을 목록으로 붙인다.
- 한국어로 간결하게 답한다.
"""


BROAD_ANSWERER_SYSTEM = """너는 공주대학교 학생을 돕는 AI 비서다.

아래 컨텍스트는 여러 공지의 요약 카드 목록이다. 사용자는 관련 공지를 한눈에 훑고 싶어한다.

규칙:
- 컨텍스트의 공지들을 목록 형태로 정리해 답한다.
  예: "현재 관련 공지는 다음과 같습니다:\n1) ○○장학 (접수 ~6/10)\n2) □□장학 (접수 ~6/15) ..."
- 각 항목에 제목과 접수기간(있으면)을 함께 보여준다.
- 컨텍스트에 없는 새로운 사실(날짜·금액·자격·연락처 등)은 만들지 마라.
- 컨텍스트가 비어 답할 공지가 전혀 없으면 "관련 공지를 찾지 못했습니다"라고 답하라.
- 내부 분석/추론 과정은 출력하지 마라. 최종 답변만 자연스럽게 출력하라.
- 답변 끝에 참고한 공지 제목과 URL을 목록으로 붙인다.
- 한국어로 간결하게 답한다.
"""


VERIFIER_SYSTEM = """너는 RAG 답변의 사실 충실도를 검증한다.

판정 규칙:
1. 답변이 사실을 단정한 경우(날짜·금액·대상·자격·연락처 등):
   - 모든 사실이 컨텍스트에 명시되어 있으면 grounded=True, fidelity=1.0.
   - 컨텍스트 사실 + 오늘 날짜에서 **논리적으로 도출되는 결론**(예: "접수 마감일이 어제 → 마감됨", "오늘이 접수기간 안 → 접수 중")은 grounded=True로 인정한다.
   - 일부만 명시되어 있으면 grounded=False, fidelity는 명시된 비율만큼.
   - 컨텍스트에 없는 내용을 단정하면 grounded=False, fidelity는 환각 비율만큼 낮춘다.

2. 답변이 "관련 공지를 찾지 못했습니다" 류의 회피인 경우:
   - 컨텍스트가 비어있다 → grounded=True, fidelity=1.0 (정직한 회피).
   - 컨텍스트가 있지만 사용자 질문 주제와 무관하다 → grounded=True, fidelity=1.0 (정직한 회피).
     예: 사용자가 '공결신청' 묻는데 컨텍스트는 '교과과정표'뿐 → 회피가 정확.
   - 컨텍스트에 사용자 질문에 답할 정보가 명백히 있는데 회피했다 → grounded=False (잘못된 회피).
     예: 사용자가 '장학금 신청' 묻고 컨텍스트에 '국가장학금 신청 일정' 공지가 있는데 회피.

note에는 의심 구간을 짧게 인용하거나 OK/회피 사유를 남긴다."""


def router_node(state: ChatState) -> dict:
    """질문을 분석해 검색 경로를 정하는 LangGraph의 라우터 노드.

    사용자 질문을 LLM에 전달해 관련 공지 카테고리와 검색용 확장 질의를
    생성하고, 이후 retriever 노드가 참고할 라우팅 정보를 상태에 추가한다.
    """
    model = get_llm().with_structured_output(RouteDecision)
    decision = model.invoke([
        SystemMessage(content=ROUTER_SYSTEM),
        HumanMessage(content=state["question"]),
    ])
    # structured_output이라 decision은 RouteDecision 인스턴스.
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
    """LangSmith retriever 카드 시각화용 래퍼."""
    q_vec = embed_query(query)
    rows = search_chunks(q_vec, major=major, categories=categories)
    return [
        {
            "url": r[0], "title": r[1], "snippet": r[2], "score": r[3],
            "posted_at": r[4], "start_date": r[5], "end_date": r[6],
            "summary": r[14] if len(r) > 14 else None,
        }
        for r in (rows or [])
    ]


# === [seungwon/bge-reranker] 시작 ===
EVIDENCE_TOP_K = RERANK_TOP_N


@traceable(run_type="retriever", name="vector_search")
def _vector_search(q_vec, major, categories):
    """trace 노출용 wrapper. output: vector similarity top-N chunk 후보 리스트."""
    return search_chunks(q_vec, major=major, categories=categories, limit=RERANK_CANDIDATES)


@traceable(name="rerank")
def _rerank(query: str, rows):
    """trace 노출용 wrapper. output: (row, cross-encoder score) 내림차순 정렬 리스트."""
    scores = rerank_scores(query, [r[2] for r in rows])
    return sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)


def _dedup_text(base: str, remove: list[str]) -> str:
    """이미 evidence chunk로 사용된 텍스트를 support document에서 제거한다."""
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
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """chunk-first retrieval + evidence chunk packing.

    1. 전체 chunk에서 vector top-N 검색
    2. chunk 단위 rerank
    3. 상위 evidence chunks 보존
    4. 관련 문서를 document-level context로 병합
    """
    q_vec = embed_query(query)
    rows = _vector_search(q_vec, major, categories)

    if not rows:
        return [], []

    ranked = _rerank(query, rows)

    evidence_ranked = ranked[:EVIDENCE_TOP_K]
    evidence_chunks: List[Dict[str, Any]] = []

    for r, s in evidence_ranked:
        evidence_chunks.append({
            "url": r[0],
            "title": r[1],
            "chunk": r[2],
            "score": s,
        })

    doc_best: dict[str, tuple[Any, float]] = {}

    for r, s in ranked:
        key = f"{r[7]}::{r[0]}"
        prev = doc_best.get(key)
        if prev is None or s > prev[1]:
            doc_best[key] = (r, s)

    top_docs = sorted(
        doc_best.values(),
        key=lambda pair: pair[1],
        reverse=True,
    )[:SUPPORT_DOC_TOP_N]

    evidence_by_url: dict[str, list[str]] = {}
    for ev in evidence_chunks:
        evidence_by_url.setdefault(ev["url"], []).append(ev["chunk"])

    contexts: List[Dict[str, Any]] = []

    for r, s in top_docs:
        full = get_document_content(r[7], r[0]) or r[2]

        deduped_full = _dedup_text(
            full,
            evidence_by_url.get(r[0], []),
        )

        contexts.append({
                "url": r[0],
                "title": r[1],
                "body_content": r[15] if len(r) > 15 else deduped_full,
                "attachment_names": r[16] if len(r) > 16 else [],
                "snippet": deduped_full,
                "score": s,
                "matched_chunk": r[2],
                "summary": r[14] if len(r) > 14 else None,
                "posted_at": r[4],
                "start_date": r[5],
                "end_date": r[6],
        })
    return contexts, evidence_chunks
# === [seungwon/bge-reranker] 끝 ===


def retriever_node(state: ChatState) -> dict:
    """라우터 결과를 바탕으로 관련 공지 컨텍스트를 검색하는 노드.

    router_node가 만든 확장 질의와 카테고리, 사용자의 전공 정보를 사용해
    chunk-first retrieval + rerank를 수행한다.
    """
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
    }


@traceable(run_type="retriever", name="search_chunks_broad")
def _retrieve_broad(
    query: str,
    major: str | None,
    categories: List[str] | None,
) -> List[Dict[str, Any]]:
    """공지당 1 chunk 후보 → rerank → 상위 문서 메타카드용 context 리스트.

    precise와 달리 evidence chunk packing / full-doc fetch 없음.
    """
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
            "start_date": r[5],
            "end_date": r[6],
            "score": s,
        }
        for r, s in top
    ]


def broad_retriever_node(state: ChatState) -> dict:
    """broad 경로 retriever. 여러 공지를 얇게 모아 카드 목록용 context를 만든다."""
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None

    contexts = _retrieve_broad(
        query,
        state.get("major"),
        categories,
    )
    return {"contexts": contexts, "evidence_chunks": []}


def _append_budget(parts: list[str], text: str, remaining: int) -> int:
    if remaining <= 0 or not text:
        return remaining
    if len(text) <= remaining:
        parts.append(text)
        return remaining - len(text)
    note = f"\n... [컨텍스트 길이 제한으로 이후 {len(text) - remaining}자 제외]"
    if remaining <= len(note):
        parts.append(text[:remaining].rstrip())
    else:
        keep = remaining - len(note)
        parts.append(text[:keep].rstrip() + note)
    return 0


def _context_header(c: Dict[str, Any]) -> str:
    sd = c.get("start_date")
    ed = c.get("end_date")
    date_line = ""
    if sd or ed:
        date_line = f"\n접수기간: {sd or '미상'} ~ {ed or '미상'}"
    return f"[{c['title']}]({c['url']}){date_line}"


def _format_context_with_budget(c: Dict[str, Any], budget: int) -> str:
    """1등 support document는 body full 우선 전략 사용.

    철학:
    - body_content는 가능한 한 full 유지
    - attachment giant stuffing 금지
    - attachment 내용은 retrieval/rerank evidence chunk로만 사용
    """
    header = _context_header(c)

    body = (
        c.get("body_content")
        or c.get("snippet")
        or ""
    ).strip()

    matched_chunk = (
        c.get("matched_chunk")
        or ""
    ).strip()

    attachment_names = c.get("attachment_names") or []

    full = f"{header}\n{body}"

    # 대부분 공지 body는 짧으므로 full 유지
    if len(full) <= budget:
        parts = [full]

        if attachment_names:
            parts.append("\n[첨부파일명]")
            parts.extend(
                f"- {name}"
                for name in attachment_names
            )

        return "\n".join(parts)

    parts = [header]
    remaining = budget - len(header)

    # body 우선 보존
    if body and remaining > 0:
        heading = "\n[본문]"
        parts.append(heading)
        remaining -= len(heading)

        body_budget = max(
            0,
            int(remaining * 0.8),
        )

        body_parts: list[str] = []

        _append_budget(
            body_parts,
            body,
            body_budget,
        )

        body_text = "\n".join(body_parts)

        parts.append(body_text)
        remaining -= len(body_text)

    # retrieval evidence chunk
    if matched_chunk and remaining > 0:
        heading = "\n[검색 매칭 청크]"
        parts.append(heading)
        remaining -= len(heading)

        remaining = _append_budget(
            parts,
            matched_chunk,
            remaining,
        )

    # attachment metadata only
    if attachment_names and remaining > 0:
        heading = "\n[첨부파일명]"
        parts.append(heading)
        remaining -= len(heading)

        attachment_text = "\n".join(
            f"- {name}"
            for name in attachment_names
        )

        remaining = _append_budget(
            parts,
            attachment_text,
            remaining,
        )

    return "\n".join(
        part
        for part in parts
        if part
    )


def _format_support_context(c: Dict[str, Any], budget: int) -> str:
    """2등 이하 보조 문서는 summary + evidence 중심 packing."""

    header = _context_header(c)

    body = (
        c.get("body_content")
        or c.get("snippet")
        or ""
    ).strip()

    matched_chunk = (
        c.get("matched_chunk")
        or ""
    ).strip()

    summary = (
        c.get("summary")
        or ""
    ).strip()

    attachment_names = c.get("attachment_names") or []

    parts = [header]
    remaining = budget - len(header)

    # summary 우선
    if summary and remaining > 0:
        heading = "\n[요약]"
        parts.append(heading)
        remaining -= len(heading)

        remaining = _append_budget(
            parts,
            summary,
            remaining,
        )

    # retrieval evidence
    if matched_chunk and remaining > 0:
        heading = "\n[검색 매칭 청크]"
        parts.append(heading)
        remaining -= len(heading)

        remaining = _append_budget(
            parts,
            matched_chunk,
            remaining,
        )

    # body 일부
    if body and remaining > 0:
        heading = "\n[본문 일부]"
        parts.append(heading)
        remaining -= len(heading)

        body_budget = max(
            0,
            int(remaining * 0.5),
        )

        body_parts: list[str] = []

        _append_budget(
            body_parts,
            body,
            body_budget,
        )

        body_text = "\n".join(body_parts)

        parts.append(body_text)
        remaining -= len(body_text)

    # attachment metadata only
    if attachment_names and remaining > 0:
        heading = "\n[첨부파일명]"
        parts.append(heading)
        remaining -= len(heading)

        attachment_text = "\n".join(
            f"- {name}"
            for name in attachment_names
        )

        remaining = _append_budget(
            parts,
            attachment_text,
            remaining,
        )

    return "\n".join(
        part
        for part in parts
        if part
    )


def _format_broad_context(
    contexts: List[Dict[str, Any]],
    budget: int,
) -> str:
    """broad 경로 packing. 공지를 얇은 메타카드(제목+기간+요약) 목록으로 렌더.

    카드 1장 = 제목/URL + 접수기간 + 요약(없으면 matched_chunk 한 줄).
    budget 안에서 카드를 가능한 한 많이 채운다.
    """
    if not contexts:
        return "(컨텍스트 없음)"

    parts: list[str] = []
    remaining = budget

    for c in contexts:
        if remaining <= 0:
            break

        header = _context_header(c)
        summary = (c.get("summary") or "").strip()
        if not summary:
            summary = (c.get("matched_chunk") or "").strip()

        card = header
        if summary:
            card += f"\n요약: {summary}"

        block = ("\n\n" if parts else "") + card
        before = len("".join(parts))
        remaining = _append_budget(parts, block, remaining)
        if len("".join(parts)) == before:
            break

    return "".join(parts).strip()


def _pack_evidence_chunks(
    evidence_chunks: List[Dict[str, Any]],
    budget: int,
) -> str:
    if not evidence_chunks or budget <= 0:
        return ""

    parts: list[str] = ["# 핵심 검색 청크"]
    remaining = budget - len(parts[0])

    for idx, ev in enumerate(evidence_chunks, 1):
        if remaining <= 0:
            break

        block = (
            f"\n\n[{idx}] {ev['title']}\n"
            f"URL: {ev['url']}\n"
            f"{ev['chunk']}"
        )

        before = len("".join(parts))
        remaining = _append_budget(parts, block, remaining)

        if len("".join(parts)) == before:
            break

    return "".join(parts).strip()


def _pack_contexts(
    contexts: List[Dict[str, Any]],
    evidence_chunks: List[Dict[str, Any]] | None = None,
    budget: int = 6000,
) -> str:
    if not contexts and not evidence_chunks:
        return "(컨텍스트 없음)"
    if budget <= 0:
        budget = 6000

    packed: list[str] = []
    remaining = budget

    evidence_text = _pack_evidence_chunks(
        evidence_chunks or [],
        max(0, int(budget * 0.35)),
    )

    if evidence_text:
        packed.append(evidence_text)
        remaining -= len(evidence_text)

    for idx, context in enumerate(contexts):
        if remaining <= 0:
            break

        separator_cost = len("\n\n---\n\n") if packed else 0
        available = remaining - separator_cost

        if available <= 0:
            break

        if idx == 0:
            rendered = _format_context_with_budget(context, available)
        else:
            rendered = _format_support_context(context, available)

        packed.append(rendered)
        remaining -= separator_cost + len(rendered)

    return "\n\n---\n\n".join(packed)


def answerer_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    if not contexts:
        return {"answer": "관련 공지를 찾지 못했습니다."}

    context_text = _pack_contexts(
        contexts,
        state.get("evidence_chunks") or [],
    )
    today = date.today().isoformat()
    model = get_llm()
    resp = model.invoke([
        SystemMessage(content=ANSWERER_SYSTEM),
        HumanMessage(content=(
            f"# 오늘 날짜\n{today}\n\n"
            f"# 사용자 질문\n{state['question']}\n\n"
            f"# 컨텍스트\n{context_text}"
        )),
    ])
    answer = resp.content if hasattr(resp, "content") else str(resp)
    return {"answer": answer}


def broad_answerer_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    if not contexts:
        return {"answer": "관련 공지를 찾지 못했습니다."}

    context_text = _format_broad_context(contexts, budget=6000)
    today = date.today().isoformat()
    model = get_llm()
    resp = model.invoke([
        SystemMessage(content=BROAD_ANSWERER_SYSTEM),
        HumanMessage(content=(
            f"# 오늘 날짜\n{today}\n\n"
            f"# 사용자 질문\n{state['question']}\n\n"
            f"# 컨텍스트\n{context_text}"
        )),
    ])
    answer = resp.content if hasattr(resp, "content") else str(resp)
    return {"answer": answer}


def verifier_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    context_text = _pack_contexts(
        contexts,
        state.get("evidence_chunks") or [],
    )
    today = date.today().isoformat()

    model = get_llm().with_structured_output(VerificationResult)
    result = model.invoke([
        SystemMessage(content=VERIFIER_SYSTEM),
        HumanMessage(content=(
            f"# 오늘 날짜\n{today}\n\n"
            f"# 답변\n{state.get('answer', '')}\n\n"
            f"# 컨텍스트\n{context_text}"
        )),
    ])
    return {
        "grounded": result.grounded,  # type: ignore[union-attr]
        "fidelity": result.fidelity,  # type: ignore[union-attr]
        "verifier_note": result.note,  # type: ignore[union-attr]
    }


def _route_by_mode(state: ChatState) -> str:
    """query_mode로 retriever 경로를 고른다. 기본 precise."""
    return "broad" if state.get("query_mode") == "broad" else "precise"


def build_graph():
    """router → (precise|broad) → answerer 이중 RAG 파이프라인을 컴파일한다.

    query_mode에 따라 precise(retriever→answerer) 또는
    broad(broad_retriever→broad_answerer)로 분기한다.
    ENABLE_VERIFIER=true면 precise answerer 뒤에만 verifier를 연결한다.
    """
    g = StateGraph(ChatState)
    g.add_node("router", router_node)
    g.add_node("retriever", retriever_node)
    g.add_node("answerer", answerer_node)
    g.add_node("broad_retriever", broad_retriever_node)
    g.add_node("broad_answerer", broad_answerer_node)

    g.set_entry_point("router")
    g.add_conditional_edges(
        "router",
        _route_by_mode,
        {"precise": "retriever", "broad": "broad_retriever"},
    )
    g.add_edge("retriever", "answerer")
    g.add_edge("broad_retriever", "broad_answerer")
    g.add_edge("broad_answerer", END)

    if ENABLE_VERIFIER:
        g.add_node("verifier", verifier_node)
        g.add_edge("answerer", "verifier")
        g.add_edge("verifier", END)
    else:
        g.add_edge("answerer", END)

    return g.compile()

GRAPH = build_graph()
