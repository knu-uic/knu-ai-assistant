from fastapi.testclient import TestClient

from api.main import app


def test_chat_maps_graph_result_to_flat_keys(monkeypatch):
    class FakeGraph:
        def invoke(self, state):
            assert state == {"question": "장학금 언제?", "major": "전자공학"}
            return {
                "answer": "6월 1일부터입니다.",
                "grounded": True,
                "fidelity": 0.92,
                "categories": ["scholarship"],
                "expanded_query": "국가장학금 신청 기간",
            }

    import api.routers.chat as chat_mod
    monkeypatch.setattr(chat_mod, "GRAPH", FakeGraph())

    with TestClient(app) as client:
        r = client.post(
            "/api/chat",
            json={"question": "장학금 언제?", "major": "전자공학"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "6월 1일부터입니다."
    assert body["grounded"] is True
    assert body["fidelity"] == 0.92
    assert body["categories"] == ["scholarship"]
    assert body["expanded_query"] == "국가장학금 신청 기간"
    assert body["verifier_note"] is None


def test_chat_defaults_when_keys_missing(monkeypatch):
    class FakeGraph:
        def invoke(self, state):
            return {"answer": "관련 공지를 찾지 못했습니다."}

    import api.routers.chat as chat_mod
    monkeypatch.setattr(chat_mod, "GRAPH", FakeGraph())

    with TestClient(app) as client:
        r = client.post("/api/chat", json={"question": "x"})

    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "관련 공지를 찾지 못했습니다."
    assert body["grounded"] is None
    assert body["categories"] == []
