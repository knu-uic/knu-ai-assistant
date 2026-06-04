import anyio
from fastapi import APIRouter

from retrieval.graph import GRAPH
from api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


def _invoke_graph(question: str, major: str | None) -> dict:
    # GRAPH는 sync 그래프. 별도 스레드에서 호출해 이벤트루프 비블로킹.
    return GRAPH.invoke({"question": question, "major": major})


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    state = await anyio.to_thread.run_sync(_invoke_graph, req.question, req.major)
    # categories는 ChatState에서 enum일 수 있음 → 문자열로 정규화(dart는 string 배열).
    categories = [getattr(c, "value", c) for c in (state.get("categories") or [])]
    return ChatResponse(
        answer=state.get("answer", ""),
        grounded=state.get("grounded"),
        fidelity=state.get("fidelity"),
        verifier_note=state.get("verifier_note"),
        categories=categories,
        expanded_query=state.get("expanded_query"),
    )
