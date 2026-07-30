from fastapi.testclient import TestClient

from api.main import app


def _parse_events(text: str) -> list[tuple[str, str]]:
    """SSE 본문을 (event, data) 튜플 목록으로 파싱."""
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(
            line.split(": ", 1) for line in block.split("\n") if ": " in line
        )
        events.append((lines.get("event"), lines.get("data")))
    return events


def test_stream_emits_steps_answer_done(monkeypatch):
    import json

    import api.sse as sse_mod

    class FakeMsg:
        content = "6월"

    class FakeGraph:
        def stream(self, state, stream_mode):
            assert state == {"question": "장학금?", "major": None}
            assert stream_mode == ["updates", "messages"]
            # 멀티모드: (mode, chunk) 튜플. updates=노드델타, messages=(msg, meta)
            yield ("updates", {"router": {"categories": ["scholarship"]}})
            yield ("updates", {"retriever": {}})
            yield ("messages", (FakeMsg(), {"langgraph_node": "answerer"}))
            yield ("updates", {"answerer": {"answer": "6월 1일부터입니다.", "grounded": True}})

    monkeypatch.setattr(sse_mod, "GRAPH", FakeGraph())

    with TestClient(app) as client:
        r = client.get("/api/chat/stream", params={"question": "장학금?"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _parse_events(r.text)
    names = [e for e, _ in events]
    assert names == ["step", "step", "token", "step", "answer", "done"]

    assert json.loads(dict(events)["token"])["text"] == "6월"

    answer = json.loads(dict(events)["answer"])
    assert answer["answer"] == "6월 1일부터입니다."
    assert answer["grounded"] is True
    assert answer["categories"] == ["scholarship"]
    # GRAPH가 안 준 키도 null로 존재 (dart Optional 대응)
    assert answer["verifier_note"] is None


def test_stream_error_event_has_korean_detail(monkeypatch):
    import json

    import api.sse as sse_mod

    class FakeGraph:
        def stream(self, state, stream_mode):
            raise RuntimeError("pipeline crashed")
            yield  # 제너레이터로 만들기 위함

    monkeypatch.setattr(sse_mod, "GRAPH", FakeGraph())

    with TestClient(app) as client:
        r = client.get("/api/chat/stream", params={"question": "x"})

    events = _parse_events(r.text)
    names = [e for e, _ in events]
    assert names == ["error", "done"]

    detail = json.loads(dict(events)["error"])["detail"]
    assert "오류" in detail
