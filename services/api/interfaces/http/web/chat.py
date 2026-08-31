"""Standalone React web chatbot endpoints."""

import json

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from retrieval.graph import GRAPH
from api.ratelimit import limiter, user_or_ip
from interfaces.http.schemas.chat import ChatRequest, ChatResponse
from api.sse import graph_events
from config import RATE_LIMIT_CHAT

router = APIRouter()


def _invoke_graph(question: str, major: str | None) -> dict:
    # GRAPH는 sync 그래프. 별도 스레드에서 호출해 이벤트루프 비블로킹.
    return GRAPH.invoke({"question": question, "major": major})


def _flat_payload(state: dict) -> dict:
    # categories는 ChatState에서 enum일 수 있음 → 문자열로 정규화(dart는 string 배열).
    categories = [getattr(c, "value", c) for c in (state.get("categories") or [])]
    return {
        "answer": state.get("answer", ""),
        "grounded": state.get("grounded"),
        "fidelity": state.get("fidelity"),
        "verifier_note": state.get("verifier_note"),
        "categories": categories,
        "expanded_query": state.get("expanded_query"),
    }


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT, key_func=user_or_ip)
async def chat(request: Request, req: ChatRequest) -> ChatResponse:
    state = await anyio.to_thread.run_sync(_invoke_graph, req.question, req.major)
    return ChatResponse(**_flat_payload(state))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/chat/stream")
@limiter.limit(RATE_LIMIT_CHAT, key_func=user_or_ip)
async def chat_stream(
    request: Request,
    question: str = Query(..., min_length=1),
    major: str | None = Query(None),
) -> StreamingResponse:
    async def gen():
        async for event, data in graph_events(question, major):
            if event == "answer":
                data = _flat_payload(data)
            elif event == "error":
                data = {"detail": "답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}
            yield _sse(event, data)
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx/프록시가 청크를 모아두지 않도록 (rev2 §6)
            "X-Accel-Buffering": "no",
        },
    )
