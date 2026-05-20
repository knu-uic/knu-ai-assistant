"""LangGraph: 라우터(분류+쿼리확장) → retriever → answerer → verifier 4노드 RAG 파이프라인."""

from datetime import date
import re
from typing import TypedDict, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langsmith import traceable

from db import search_chunks
# === [seungwon/bge-reranker] 시작 ===
from db import get_document_content
from rerank import rerank_scores
# === [seungwon/bge-reranker] 끝 ===
from embed import embed_query
from model import get_llm


Category = Literal["장학/등록", "학사/수업", "진로/취업", "행사/공모전", "일반/기타"]


class RouteDecision(BaseModel):
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
    major: str | None
    categories: List[Category]
    expanded_query: str
    route_rationale: str
    contexts: List[Dict[str, Any]]
    answer: str
    grounded: bool
    fidelity: float
    verifier_note: str


ROUTER_SYSTEM = """너는 공주대 학생 질문을 분석해 RAG 파이프라인의 진입점을 결정하는 라우터다.

## 카테고리 분류 (categories)
다음 5개 중 질문과 관련 있는 카테고리를 모두 고른다.
1. 장학/등록 — 국가장학금, 등록금 납부, 학자금 대출 등
2. 학사/수업 — 수강신청, 휴학·복학, 졸업요건, 성적, 교과과정표, 학점
3. 진로/취업 — 채용, 인턴, 자격증, 취업특강, 진로상담
4. 행사/공모전 — 대회, 해커톤, 동아리, 축제, 세미나
5. 일반/기타 — 분실물, 시설, 예비군, 위 4개에 속하지 않는 그 외

- 질문이 한 카테고리에 명확하면 1개만.
- 두 영역에 걸치거나 모호하면 여러 개. 진짜 광범위하면 5개 전부.

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
아래 컨텍스트만 근거로 답하라.
- 컨텍스트에 명시된 사실에서 **논리적으로 도출되는 결론**은 허용한다.
  예: 오늘 날짜와 컨텍스트의 start_date/end_date를 비교해 "현재 접수 중", "이미 마감" 같이 판단하는 것.
- 단, 컨텍스트에 없는 **새로운 사실**(날짜·금액·자격·연락처 등)을 만들어내지 마라.
- 컨텍스트에 사용자 질문에 답할 정보가 전혀 없을 때만 "관련 공지를 찾지 못했습니다"라고 답한다.
- 답변 끝에 참고한 공지 제목과 URL을 목록으로 붙인다.
- 한국어로 간결하게 답한다."""


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
    rows = search_chunks(q_vec, major=major, categories=categories, limit=5)
    return [
        {
            "url": r[0], "title": r[1], "snippet": r[2], "score": r[3],
            "posted_at": r[4], "start_date": r[5], "end_date": r[6],
            "summary": r[14] if len(r) > 14 else None,
        }
        for r in (rows or [])
    ]


# === [seungwon/bge-reranker] 시작 ===
# 원래 seungwon/bge-reranker 브랜치는 config.py에서 import하던 상수.
# 한정우 환경(설정 파일 보호)을 위해 모듈 상수로 인라인.
RERANK_CANDIDATES = 15  # vector 1차 후보 수
RERANK_TOP_N = 3        # cross-encoder 통과 후 최종 컨텍스트 수
ANSWER_CONTEXT_CHAR_BUDGET = 9000
ATTACHMENT_NAME_RESERVE = 1200


@traceable(run_type="retriever", name="vector_search")
def _vector_search(q_vec, major, categories):
    """trace 노출용 wrapper. output: vector top-N 후보 row 리스트(reranker 입력)."""
    return search_chunks(q_vec, major=major, categories=categories, limit=RERANK_CANDIDATES)


@traceable(name="rerank")
def _rerank(query: str, rows):
    """trace 노출용 wrapper. output: (row, cross-encoder score) 내림차순 정렬 리스트."""
    scores = rerank_scores(query, [r[2] for r in rows])
    return sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)


@traceable(run_type="retriever", name="search_chunks_reranked")
def _retrieve_with_rerank(
    query: str,
    major: str | None,
    categories: List[str] | None,
) -> List[Dict[str, Any]]:
    """vector top-N → BGE-reranker로 재정렬 → top-K → 각 doc 풀문서 전달.

    score 필드는 cross-encoder 점수(0~1)로 덮어쓴다.
    snippet은 document 전체 content, matched_chunk는 실제 검색/리랭크된 대표 청크.
    """
    q_vec = embed_query(query)
    rows = _vector_search(q_vec, major, categories)
    if not rows:
        return []
    ranked = _rerank(query, rows)[:RERANK_TOP_N]
    contexts: List[Dict[str, Any]] = []
    for r, s in ranked:
        full = get_document_content(r[7], r[0])
        snippet = full or r[2]
        contexts.append({
            "url": r[0], "title": r[1], "snippet": snippet, "score": s,
            "matched_chunk": r[2],
            "summary": r[14] if len(r) > 14 else None,
            "posted_at": r[4], "start_date": r[5], "end_date": r[6],
        })
    return contexts
# === [seungwon/bge-reranker] 끝 ===


def retriever_node(state: ChatState) -> dict:
    """라우터 결과를 바탕으로 관련 공지 컨텍스트를 검색하는 노드.

    router_node가 만든 확장 질의와 카테고리, 사용자의 전공 정보를 사용해
    벡터 저장소에서 관련 공지 조각을 찾고 answerer_node가 참고할 contexts를
    상태에 추가한다.
    """
    # 라우터가 확장한 쿼리로 임베딩. 빈 문자열이면 원본 질문으로 폴백.
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None
    contexts = _retrieve_with_rerank(query, state.get("major"), categories)  # [seungwon/bge-reranker] _retrieve → _retrieve_with_rerank
    return {"contexts": contexts}


_ATTACHMENT_RE = re.compile(r"^\[첨부: (?P<name>.+?)\]\s*$", re.MULTILINE)


def _split_content(content: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(_ATTACHMENT_RE.finditer(content or ""))
    if not matches:
        return content or "", []

    body = content[:matches[0].start()].strip()
    attachments: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        attachments.append((match.group("name").strip(), content[start:end].strip()))
    return body, attachments


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
    """답변 생성용 컨텍스트.

    길면 검색/리랭크가 실제로 고른 청크를 먼저 보존한 뒤,
    본문 > 첨부파일명 > 첨부내용 순으로 남은 공간을 채운다.
    """
    header = _context_header(c)
    content = c.get("snippet") or ""
    matched_chunk = (c.get("matched_chunk") or "").strip()
    full = f"{header}\n{content}"
    if len(full) <= budget:
        return full

    body, attachments = _split_content(content)
    attachment_names = "\n".join(f"- {name}" for name, _ in attachments)
    attachment_contents = "\n\n".join(
        f"[첨부: {name}]\n{text}" for name, text in attachments if text
    )
    name_heading = "\n[첨부파일명]"

    parts = [header]
    remaining = budget - len(header)

    if matched_chunk:
        matched_heading = "\n[검색 매칭 청크]"
        parts.append(matched_heading)
        remaining -= len(matched_heading)
        remaining = _append_budget(parts, matched_chunk, remaining)

    body_heading = "\n[본문]"
    parts.append(body_heading)
    remaining -= len(body_heading)
    name_reserve = (
        min(len(name_heading) + len(attachment_names), ATTACHMENT_NAME_RESERVE)
        if attachment_names else 0
    )
    body_budget = max(0, remaining - name_reserve)

    body_parts: list[str] = []
    _append_budget(body_parts, body, body_budget)
    body_text = "\n".join(body_parts)
    parts.append(body_text)
    remaining -= len(body_text)

    if attachment_names and remaining > 0:
        parts.append(name_heading)
        remaining -= len(name_heading)
        remaining = _append_budget(parts, attachment_names, remaining)

    if attachment_contents and remaining > 0:
        heading = "\n[첨부파일 내용]"
        parts.append(heading)
        remaining -= len(heading)
        _append_budget(parts, attachment_contents, remaining)

    return "\n".join(part for part in parts if part)


def _format_context(c: Dict[str, Any]) -> str:
    """answerer/verifier 공용 fallback 포맷."""
    return f"{_context_header(c)}\n{c.get('snippet') or ''}"


def _format_support_context(c: Dict[str, Any], budget: int) -> str:
    """2등 이하 보조 문서는 요약 + 매칭 청크 중심으로 짧게 넣는다."""
    header = _context_header(c)
    content = c.get("snippet") or ""
    matched_chunk = (c.get("matched_chunk") or "").strip()
    summary = (c.get("summary") or "").strip()
    _, attachments = _split_content(content)
    attachment_names = "\n".join(f"- {name}" for name, _ in attachments)

    parts = [header]
    remaining = budget - len(header)

    if summary and remaining > 0:
        heading = "\n[요약]"
        parts.append(heading)
        remaining -= len(heading)
        remaining = _append_budget(parts, summary, remaining)

    if matched_chunk and remaining > 0:
        heading = "\n[검색 매칭 청크]"
        parts.append(heading)
        remaining -= len(heading)
        remaining = _append_budget(parts, matched_chunk, remaining)

    if attachment_names and remaining > 0:
        heading = "\n[첨부파일명]"
        parts.append(heading)
        remaining -= len(heading)
        _append_budget(parts, attachment_names, remaining)

    return "\n".join(part for part in parts if part)


def _pack_contexts(contexts: List[Dict[str, Any]], budget: int = ANSWER_CONTEXT_CHAR_BUDGET) -> str:
    if not contexts:
        return "(컨텍스트 없음)"

    packed: list[str] = []
    remaining = budget
    for idx, context in enumerate(contexts):
        if remaining <= 0:
            break

        full = _format_context(context)
        separator_cost = len("\n\n---\n\n") if packed else 0
        available = remaining - separator_cost
        if available <= 0:
            break

        if idx == 0 and len(full) <= available:
            rendered = full
        elif idx == 0:
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

    context_text = _pack_contexts(contexts)
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


def verifier_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    context_text = _pack_contexts(contexts)
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


def build_graph():
    """LangGraph RAG 파이프라인을 구성하고 실행 가능한 그래프로 컴파일한다.

    router -> retriever -> answerer -> verifier 순서로 노드를 연결해
    질문 분류, 공지 검색, 답변 생성, 근거 검증까지 이어지는 흐름을 만든다.
    반환된 그래프는 앱 시작 시 GRAPH 상수에 바인딩되어 재사용된다.
    각 노드는 ChatState를 공유하며 이전 노드의 결과를 다음 노드 입력으로 넘긴다.
    """
    g = StateGraph(ChatState)
    g.add_node("router", router_node)
    g.add_node("retriever", retriever_node)
    g.add_node("answerer", answerer_node)
    g.add_node("verifier", verifier_node)

    g.set_entry_point("router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "answerer")
    g.add_edge("answerer", "verifier")
    g.add_edge("verifier", END)
    return g.compile()

GRAPH = build_graph()
