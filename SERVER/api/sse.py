"""sync GRAPH.stream → async SSE 브리지.

GRAPH.stream은 sync 제너레이터라 async 핸들러에서 직접 돌리면
이벤트루프가 노드 실행 내내 멈춘다. 별도 스레드에서 돌리고
노드 이벤트를 asyncio.Queue로 넘긴다. (설계문서 rev2 §6 D11)
"""
import asyncio
import threading
import traceback
from typing import AsyncIterator

from retrieval.graph import GRAPH


async def graph_events(
    question: str, major: str | None
) -> AsyncIterator[tuple[str, dict]]:
    """("step"|"answer"|"error", payload) 튜플을 순서대로 내보낸다.

    - step: 노드 하나 완료 {"node": 이름, "status": "done"}
    - answer: 최종 누적 state (flat 매핑은 라우터 책임)
    - error: 파이프라인 예외 (유저용 메시지는 라우터에서 생성)
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def _put(item: tuple[str, dict] | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def _run() -> None:
        state: dict = {}
        try:
            for update in GRAPH.stream(
                {"question": question, "major": major}, stream_mode="updates"
            ):
                for node, delta in update.items():
                    state.update(delta or {})
                    _put(("step", {"node": node, "status": "done"}))
            _put(("answer", state))
        except Exception:
            traceback.print_exc()
            _put(("error", {}))
        finally:
            _put(None)

    threading.Thread(target=_run, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
