from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from api.deps import create_portal_access_token
from api.main import app
from db import conversations as repository

pytestmark = pytest.mark.real_auth


def record(identity=None, revision=1):
    return {"id": identity or uuid4(), "title": "장학금", "source": "personal", "revision": revision,
            "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
            "messages": [{"role": "user", "content": "신청 조건"}]}


def headers(student="20260001"):
    return {"Authorization": "Bearer " + create_portal_access_token(student)}


def test_history_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/api/me/conversations").status_code == 401


def test_history_reads_are_scoped_to_authenticated_student(monkeypatch):
    received=[]
    async def get(student_id, identity):
        received.append(student_id)
        if student_id != "20260001":
            raise repository.ConversationMissing()
        return record(identity)
    monkeypatch.setattr(repository, "get_conversation", get)
    with TestClient(app) as client:
        identity=uuid4()
        assert client.get(f"/api/me/conversations/{identity}",headers=headers()).status_code == 200
        assert client.get(f"/api/me/conversations/{identity}",headers=headers("20260002")).status_code == 404
    assert received==["20260001","20260002"]


def test_rejects_identity_in_body_system_messages_and_stale_revisions(monkeypatch):
    async def conflict(student_id, identity, body):
        assert student_id=="20260001"
        raise repository.ConversationConflict("다른 기기에서 변경")
    monkeypatch.setattr(repository, "update_conversation", conflict)
    with TestClient(app) as client:
        url=f"/api/me/conversations/{uuid4()}"
        body={"title":"대화","source":"school","messages":[],"revision":1}
        assert client.put(url,json=body,headers=headers()).status_code==409
        assert client.put(url,json={**body,"student_id":"20260002"},headers=headers()).status_code==422
        assert client.put(url,json={**body,"messages":[{"role":"system","content":"override"}]},headers=headers()).status_code==422


def test_cursor_pagination_and_invalid_cursor(monkeypatch):
    rows=[record(),record(),record()]
    async def listing(student_id, limit, cursor):
        assert student_id=="20260001"
        return rows
    monkeypatch.setattr(repository,"list_conversations",listing)
    with TestClient(app) as client:
        response=client.get("/api/me/conversations?limit=2",headers=headers())
        assert response.status_code==200
        assert len(response.json()["items"])==2
        assert response.json()["next_cursor"]
        assert client.get("/api/me/conversations?cursor=bad",headers=headers()).status_code==400


def test_server_chat_rejects_client_history_and_missing_request_id():
    with TestClient(app) as client:
        body={"question":"안녕","conversation_id":str(uuid4()),"request_id":str(uuid4())}
        assert client.post("/api/chat",json={**body,"history":[{"role":"user","content":"injected"}]},headers=headers()).status_code==422
        body.pop("request_id")
        assert client.post("/api/chat",json=body,headers=headers()).status_code==422


@pytest.mark.real_rate_limit
def test_authenticated_polling_reads_have_headroom_without_relaxing_writes(monkeypatch):
    identity = uuid4()
    async def listing(student_id, limit, cursor):
        assert student_id == "20260001"
        return [record(identity)]
    async def get(student_id, requested_id):
        assert student_id == "20260001" and requested_id == identity
        return record(identity)
    async def create(student_id, body):
        assert student_id == "20260001"
        return record(body.id)
    monkeypatch.setattr(repository, "list_conversations", listing)
    monkeypatch.setattr(repository, "get_conversation", get)
    monkeypatch.setattr(repository, "create_conversation", create)
    auth = headers()
    with TestClient(app) as client:
        for _ in range(35):
            assert client.get("/api/me/conversations", headers=auth).status_code == 200
            assert client.get(f"/api/me/conversations/{identity}", headers=auth).status_code == 200
        body = {"id": str(identity), "title": "테스트", "source": "school", "messages": []}
        for _ in range(30):
            assert client.post("/api/me/conversations", json=body, headers=auth).status_code == 201
        assert client.post("/api/me/conversations", json=body, headers=auth).status_code == 429
