"""LangGraph: 라우터(분류+쿼리확장) → retriever → answerer → verifier 4노드 RAG 파이프라인."""

from datetime import date
from typing import TypedDict, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langsmith import traceable
from config import RERANK_CANDIDATES, RERANK_TOP_N
from db import search_chunks, get_document_content
from embed import embed_query
from model import get_model
from rerank import rerank_scores


Category = Literal["장학/등록", "학사/수업", "진로/취업", "행사/공모전", "일반/기타", "규정/학칙"]


class RouteDecision(BaseModel):
    intent: Literal["rag", "casual"] = Field(
        description="인사·감사·챗봇 자기소개·범위 밖(날씨 등)이면 casual. "
                    "학사·공지·장학·교과·취업 등 검색이 필요한 질문이면 rag."
    )
    categories: List[Category] = Field(
        description="검색할 카테고리 리스트. intent=='rag'일 때만 의미 있음. "
                    "casual이면 빈 리스트 허용. 모호하면 여러 개, 명확히 무관하면 1개만."
    )
    expanded_query: str = Field(
        description="임베딩 검색용으로 다듬은 standalone 쿼리. intent=='rag'일 때만 의미 있음. "
                    "casual이면 빈 문자열 허용. 이전 대화의 대명사/생략어는 모두 풀어 self-contained로 쓴다. "
                    "공지 제목의 격식체와 도메인 유의어를 반영하고 '알려줘/조회해' 같은 서술어는 제거한다."
    )
    rationale: str = Field(description="intent·분류·확장 결정 이유 한 줄")


class VerificationResult(BaseModel):
    grounded: bool = Field(description="답변의 핵심 사실이 컨텍스트에 명시되어 있으면 True")
    fidelity: float = Field(description="0.0(전부 환각)~1.0(전부 근거 있음)")
    note: str = Field(description="할루시네이션이 의심되는 부분 또는 OK 사유")


class ChatState(TypedDict, total=False):
    question: str
    major: str | None
    history: List[Dict[str, str]]
    intent: Literal["rag", "casual"]
    categories: List[Category]
    expanded_query: str
    route_rationale: str
    contexts: List[Dict[str, Any]]
    answer: str
    grounded: bool
    fidelity: float
    verifier_note: str


ROUTER_SYSTEM = """너는 공주대 학생 질문을 분석해 RAG 파이프라인의 진입점을 결정하는 라우터다.

## 의도 분류 (intent)
질문을 두 가지 중 하나로 분류한다.

- **casual** — 인사·감사·잡담·챗봇 자기소개·범위 밖 질문.
  - 예: "안녕하세요", "고마워요", "넌 누구야?", "너 뭐 할 수 있어?", "오늘 날씨 어때?", "1+1은?"
  - casual이면 categories=[], expanded_query="" 로 둔다(어차피 검색 안 함).
- **rag** — 공주대 학사·공지·장학·교과·취업 정보가 필요한 질문.
  - 예: "장학금 신청 언제까지야?", "졸업학점 얼마야", "캡스톤 신청 어떻게 해?"

## 카테고리 분류 (categories, intent=='rag'일 때만)
다음 6개 중 질문과 관련 있는 카테고리를 모두 고른다.
1. 장학/등록 — 국가장학금, 등록금 납부, 학자금 대출 등
2. 학사/수업 — 수강신청, 휴학·복학, 졸업요건, 성적, 교과과정표, 학점
3. 진로/취업 — 채용, 인턴, 자격증, 취업특강, 진로상담
4. 행사/공모전 — 대회, 해커톤, 동아리, 축제, 세미나
5. 일반/기타 — 분실물, 시설, 예비군, 위 4개에 속하지 않는 그 외
6. 규정/학칙 — 학칙, 학사관리규정, 등록금규정 등 학교 공식 규정/조항

- 질문이 한 카테고리에 명확하면 1개만.
- 두 영역에 걸치거나 모호하면 여러 개. 진짜 광범위하면 6개 전부.

## 쿼리 확장 (expanded_query, intent=='rag'일 때만)
공지 제목은 격식체("○○ 모집 안내", "○○ 신청 기간")이고 학생 질문은 구어체라 임베딩 공간에서 거리가 멀다. 다음을 적용해 검색용 쿼리로 다듬는다.

- **이전 대화가 주어진 경우 follow-up을 self-contained로 재작성한다.** 대명사("그거", "그 중")·생략된 주제어를 직전 대화의 주제로 채워 넣는다.
  - 예: 직전 답변이 "국가장학금 1차 신청 안내…"이고 현재 질문이 "신청 마감 언제야?" → expanded_query="국가장학금 1차 신청 마감일"
  - 예: 직전 답변이 "캡스톤 디자인 팀 신청 안내…"이고 현재 질문이 "그거 어디서 해?" → expanded_query="캡스톤 디자인 팀 신청 방법"
- '알려줘', '조회해', '보여줘', '어떻게 돼' 같은 서술어/조사 제거.
- 핵심 명사 + 도메인 유의어/격식어 2~4개 추가 (과확장 금지).
  - 예: "장학금 알려줘" → "장학금 신청 안내 모집"
  - 예: "졸업학점 얼마야" → "졸업요건 이수학점 졸업기준"
- 사용자가 명시한 고유명사(학과, 행사명, 자격증명)는 그대로 유지.
- 너무 많이 늘리면 임베딩 평균이 흐려져 오히려 검색 품질이 떨어진다 — 짧고 정확하게.

## rationale
intent·카테고리·확장을 그렇게 고른 이유를 한 줄로.
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


def _history_messages(history: List[Dict[str, str]] | None) -> list:
    """history dict 리스트를 LangChain Human/AI 메시지로 변환."""
    msgs: list = []
    for turn in history or []:
        cls = HumanMessage if turn.get("role") == "user" else AIMessage
        msgs.append(cls(content=turn.get("content", "")))
    return msgs


def router_node(state: ChatState) -> dict:
    model = get_model().with_structured_output(RouteDecision)
    messages = (
        [SystemMessage(content=ROUTER_SYSTEM)]
        + _history_messages(state.get("history"))
        + [HumanMessage(content=state["question"])]
    )
    decision = model.invoke(messages)
    # structured_output이라 decision은 RouteDecision 인스턴스.
    return {
        "intent": decision.intent,  # type: ignore[union-attr]
        "categories": list(decision.categories),  # type: ignore[union-attr]
        "expanded_query": decision.expanded_query,  # type: ignore[union-attr]
        "route_rationale": decision.rationale,  # type: ignore[union-attr]
    }

@traceable(run_type="retriever", name="vector_search")                                          
def _vector_search(q_vec, major, categories):                                                   
    """trace 노출용 wrapper. output: vector top-N 후보 row 리스트(reranker 입력)."""            
    return search_chunks(q_vec, major=major, categories=categories, limit=RERANK_CANDIDATES)    
                                                                                                
                                                                                                
@traceable(name="rerank")                                                                       
def _rerank(query: str, rows):                                                                  
    """trace 노출용 wrapper. output: (row, cross-encoder score) 내림차순 정렬 리스트."""        
    scores = rerank_scores(query, [r[2] for r in rows])                                         
    return sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)                    
                                                                                                
                                                                                               

@traceable(run_type="retriever", name="search_chunks")
def _retrieve(
    query: str,
    major: str | None,
    categories: List[str] | None,
) -> List[Dict[str, Any]]:
    """vector top-N(청크 단위) → BGE-reranker로 재정렬 → top-K 청크 → 부모 문서 dedupe.

    같은 url의 청크가 top-K 안에 여러 개 들어오면 가장 높은 rerank score 1개만 남기고
    그 문서의 fulldoc만 LLM에 전달한다. 한 문서가 정답인 질문에서 컨텍스트 비대로 인한
    할루시네이션을 피한다.

    score 필드는 cross-encoder 점수(0~1)로 덮어쓴다.
    원래의 임베딩 코사인 점수는 디버깅 외 용도가 없어 보존하지 않는다.
    """
    q_vec = embed_query(query)
    rows = _vector_search(q_vec, major, categories)
    if not rows:
        return []
    ranked = _rerank(query, rows)[:RERANK_TOP_N]
    contexts: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for r, s in ranked:
        url = r[0]
        # if url in seen_urls:
        #     continue
        # seen_urls.add(url)
        # full = get_document_content(r[7], url)
        # snippet = full or r[2]
        snippet = r[2] # 청크만
        contexts.append({
            "url": url, "title": r[1], "snippet": snippet, "score": s,
            "posted_at": r[4], "start_date": r[5], "end_date": r[6],
        })
    return contexts


def retriever_node(state: ChatState) -> dict:
    # 라우터가 확장한 쿼리로 임베딩. 빈 문자열이면 원본 질문으로 폴백.
    query = state.get("expanded_query") or state["question"]
    categories = list(state.get("categories") or []) or None
    contexts = _retrieve(query, state.get("major"), categories)
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
    messages = (
        [SystemMessage(content=ANSWERER_SYSTEM)]
        + _history_messages(state.get("history"))
        + [HumanMessage(content=(
            f"# 오늘 날짜\n{today}\n\n"
            f"# 사용자 질문\n{state['question']}\n\n"
            f"# 컨텍스트\n{context_text}"
        ))]
    )
    resp = model.invoke(messages)
    answer = resp.content if hasattr(resp, "content") else str(resp)
    return {"answer": answer}


CASUAL_SYSTEM = """너는 공주대 학생을 돕는 AI 비서다.
인사·감사·자기소개·범위 밖 질문에는 짧고 친근하게 답한다.
- 학사·공지·장학·취업 등 검색이 필요한 질문이면 그 사실을 안내한다("○○에 대해 더 구체적으로 물어보면 공지를 찾아드릴게요" 같은 톤).
- 범위 밖(날씨, 일반 상식 등)은 정중히 거절하고 도울 수 있는 영역을 제시한다.
- 한국어 1~3문장."""


def casual_answerer_node(state: ChatState) -> dict:
    model = get_model()
    messages = (
        [SystemMessage(content=CASUAL_SYSTEM)]
        + _history_messages(state.get("history"))
        + [HumanMessage(content=state["question"])]
    )
    resp = model.invoke(messages)
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
    g.add_node("casual_answerer", casual_answerer_node)

    g.set_entry_point("router")
    g.add_conditional_edges(
        "router",
        lambda s: s.get("intent", "rag"),
        {"rag": "retriever", "casual": "casual_answerer"},
    )
    g.add_edge("retriever", "answerer")
    g.add_edge("answerer", END)
    # g.add_edge("verifier", END)
    g.add_edge("casual_answerer", END)
    return g.compile()


GRAPH = build_graph()
