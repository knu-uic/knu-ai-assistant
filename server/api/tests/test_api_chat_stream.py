import json

import pytest
from fastapi.testclient import TestClient

from api.deps import create_portal_access_token
from api.main import app


def _parse_events(text: str) -> list[tuple[str, str]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        events.append((lines.get("event"), lines.get("data")))
    return events


@pytest.mark.real_auth
def test_stream_emits_step_answer_done(monkeypatch):
    import interfaces.http.web.chat as chat

    async def active(student_id):
        return {"model": "test", "provider": "openai", "secret": {"api_key": "test"}}

    async def answer(student_id, question, history):
        assert student_id == "20260001"
        assert question == "장학금?"
        return "6월 1일부터입니다."

    monkeypatch.setattr(chat, "_active_account", active)
    monkeypatch.setattr(chat, "answer", answer)
    with TestClient(app) as client:
        token = create_portal_access_token("20260001")
        response = client.post("/api/chat/stream", json={"question": "장학금?"},
                               headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_events(response.text)
    assert [name for name, _ in events] == ["step", "token", "answer", "done"]
    assert json.loads(dict(events)["token"])["text"] == "6월 1일부터입니다."


@pytest.mark.real_auth
def test_stream_error_event_has_korean_detail(monkeypatch):
    import interfaces.http.web.chat as chat

    async def active(student_id):
        return {"model": "test", "provider": "openai", "secret": {"api_key": "test"}}

    async def fail(student_id, question, history):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(chat, "_active_account", active)
    monkeypatch.setattr(chat, "answer", fail)
    with TestClient(app) as client:
        token = create_portal_access_token("20260001")
        response = client.post("/api/chat/stream", json={"question": "x"},
                               headers={"Authorization": f"Bearer {token}"})

    events = _parse_events(response.text)
    assert [name for name, _ in events] == ["step", "error", "done"]
    assert "확인" in json.loads(dict(events)["error"])["detail"]
