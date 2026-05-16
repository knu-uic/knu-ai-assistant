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
from rerank import rerank_scores
# === [seungwon/bge-reranker] 끝 ===
from embed import embed_query
from model import get_model


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
    model = get_model().with_structured_output(RouteDecision)
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
        }
        for r in (rows or [])
    ]


# === [seungwon/bge-reranker] 시작 ===
# 원래 seungwon/bge-reranker 브랜치는 config.py에서 import하던 상수.
# 한정우 환경(설정 파일 보호)을 위해 모듈 상수로 인라인.
RERANK_CANDIDATES = 15  # vector 1차 후보 수
RERANK_TOP_N = 3        # cross-encoder 통과 후 최종 컨텍스트 수


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
    snippet은 매칭 청크가 아닌 document 전체 content (표 등 정보 손실 방지).
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
            "posted_at": r[4], "start_date": r[5], "end_date": r[6],
        })
    return contexts
# === [seungwon/bge-reranker] 끝 ===


def retriever_node(state: ChatState) -> dict:
    # 라우터가 확장한 쿼리로 임베딩. 빈 문자열이면 원본 질문으로 폴백.
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None
    contexts = _retrieve_with_rerank(query, state.get("major"), categories)  # [seungwon/bge-reranker] _retrieve → _retrieve_with_rerank
    return {"contexts": contexts}


def _format_context(c: Dict[str, Any]) -> str:
    """answerer/verifier 공용 컨텍스트 포맷. start/end_date를 명시적으로 노출."""
    sd = c.get("start_date")
    ed = c.get("end_date")
    date_line = ""
    if sd or ed:
        date_line = f"\n접수기간: {sd or '미상'} ~ {ed or '미상'}"
    return f"[{c['title']}]({c['url']}){date_line}\n{c['snippet']}"


def answerer_node(state: ChatState) -> dict:
    contexts = state.get("contexts") or []
    if not contexts:
        return {"answer": "관련 공지를 찾지 못했습니다."}

    context_text = "\n\n---\n\n".join(_format_context(c) for c in contexts)
    today = date.today().isoformat()
    model = get_model()
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
    context_text = "\n\n---\n\n".join(
        _format_context(c) for c in contexts
    ) or "(컨텍스트 없음)"
    today = date.today().isoformat()

    model = get_model().with_structured_output(VerificationResult)
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
