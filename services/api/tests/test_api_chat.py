from fastapi.testclient import TestClient
import pytest

from api.deps import create_portal_access_token
from api.main import app


@pytest.mark.real_auth
def test_chat_passes_history_to_student_agent(monkeypatch):
    import interfaces.http.web.chat as chat_mod

    received = []

    async def fake_answer(student_id, question, history):
        received.append((student_id, question, [(m.role, m.content) for m in history]))
        return "6월 1일부터입니다."

    monkeypatch.setattr(chat_mod, "answer", fake_answer)
    with TestClient(app) as client:
        token = create_portal_access_token("20260001")
        response = client.post("/api/chat", json={
            "question": "언제?", "history": [{"role": "user", "content": "장학금 신청"}],
        }, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"answer": "6월 1일부터입니다."}
    assert received == [("20260001", "언제?", [("user", "장학금 신청")])]
