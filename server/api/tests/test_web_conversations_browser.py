"""Opt-in UI regression. All API calls are mocked; no school/LLM requests."""
import base64
import json
import os
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

URL = os.environ.get("KNU_WEB_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Set KNU_WEB_TEST_URL to a local Vite server")


def test_web_server_history_and_failure_recovery(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    assert urlparse(URL).hostname in {"localhost", "127.0.0.1"}, "Local test server only"
    token = "mock." + base64.urlsafe_b64encode(json.dumps({"sub": "portal:TEST"}).encode()).decode().rstrip("=") + ".mock"
    identity = str(uuid4())
    original = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"원본 기록 {i}"} for i in range(20)]
    conversations = {identity: {"id": identity, "title": "서버에 저장된 대화", "source": "personal",
        "revision": 7, "messages": original.copy(), "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}}
    requests, failures = [], []
    mode = {"reply": "normal", "expired": False}

    def api(route):
        path = urlparse(route.request.url).path.removeprefix("/api")
        method = route.request.method
        status, data = 200, {}
        try:
            if path == "/auth/portal-login":
                data = {"access_token": token}
            elif path == "/me":
                data = {"student_id": "TEST", "name": "화면 테스트", "major": "컴퓨터공학과", "year": 3}
            elif path == "/me/conversations":
                data = {"items": [{k: v for k, v in c.items() if k != "messages"} for c in conversations.values()], "next_cursor": None}
            elif path.startswith("/me/conversations/"):
                key = path.rsplit("/", 1)[1]
                if key not in conversations:
                    status, data = 404, {"detail": "대화를 찾을 수 없습니다."}
                elif method == "DELETE":
                    del conversations[key]
                    status = 204
                else:
                    data = conversations[key]
            elif path == "/chat/models":
                if mode["expired"]:
                    status, data = 401, {"detail": "expired"}
                else:
                    data = {"school": {"available": True, "model": "mock"}}
            elif path == "/chat/stream":
                body = route.request.post_data_json
                assert "history" not in body
                UUID(body["conversation_id"]); UUID(body["request_id"])
                requests.append(body)
                key = body["conversation_id"]
                if mode["reply"] == "conflict":
                    route.fulfill(content_type="text/event-stream", body='event: error\ndata: {"detail":"다른 기기에서 변경되었습니다.","status":409}\n\n')
                    return
                c = conversations.get(key) or {"id": key, "title": body["question"], "source": body["source"],
                    "revision": 1, "messages": [], "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
                assert body["revision"] == (c["revision"] if key in conversations else 0)
                c["messages"] += [{"role": "user", "content": body["question"]}, {"role": "assistant", "content": "저장된 답변: " + body["question"]}]
                c["revision"] += 1
                conversations[key] = c
                event = "event: answer\ndata: " + json.dumps({"answer": c["messages"][-1]["content"], "conversation": c}, ensure_ascii=False) + "\n\n"
                if mode["reply"] != "lost":
                    event += "event: done\ndata: {}\n\n"
                route.fulfill(content_type="text/event-stream", body=event)
                return
            elif path == "/me/timetable":
                data = {"timetable": []}
            elif path == "/me/home":
                data = {"recommended": [], "deadlines": []}
            else:
                raise AssertionError(f"Unexpected mocked endpoint: {method} {path}")
        except Exception as exc:
            failures.append(str(exc)); status, data = 500, {"detail": "mock assertion failed"}
        route.fulfill(status=status, content_type="application/json", body="" if status == 204 else json.dumps(data, ensure_ascii=False))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        context.route("**/api/**", api)
        page = context.new_page()
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(URL)
        page.locator('input[autocomplete="username"]').fill("TEST")
        page.locator('input[type="password"]').fill("mock-password")
        page.get_by_role("button", name="로그인", exact=True).click()
        page.get_by_role("button", name="AI 챗봇", exact=True).click()
        expect(page.get_by_text("원본 기록 0", exact=True)).to_be_visible()
        question = page.get_by_placeholder("KNU에 대해 질문하기...")
        expect(question).to_be_enabled()
        question.fill("맥락 이어서 질문"); question.press("Enter")
        expect(page.get_by_text("저장된 답변: 맥락 이어서 질문", exact=True)).to_be_visible()
        assert requests[-1]["revision"] == 7 and len(conversations[identity]["messages"]) == 22
        page.reload()
        page.get_by_role("button", name="AI 챗봇", exact=True).click()
        expect(page.get_by_text("저장된 답변: 맥락 이어서 질문", exact=True)).to_be_visible()

        # Other-device changes are displayed after an explicit server refresh.
        conversations[identity]["messages"] += [{"role": "user", "content": "다른 기기 질문"}, {"role": "assistant", "content": "다른 기기 답변"}]
        conversations[identity]["revision"] += 1
        page.get_by_role("button", name="대화 목록 열기").click()
        page.get_by_role("button", name="서버 기록 새로고침").click()
        expect(page.get_by_text("다른 기기 답변", exact=True)).to_be_visible()
        page.get_by_role("button", name="새 대화", exact=True).click()
        expect(question).to_be_enabled()
        mode["reply"] = "lost"
        question.fill("연결 끊김 복원"); question.press("Enter")
        expect(page.locator('.chat-history-feedback')).to_have_text("답변 연결은 끊겼지만 서버에 저장된 답변을 복원했습니다.")
        expect(question).to_have_value("")
        assert requests[-1]["conversation_id"] != identity and requests[-1]["revision"] == 0

        # A conflicting/failed turn must not fabricate an assistant message.
        expect(question).to_be_enabled()
        mode["reply"] = "conflict"
        question.fill("충돌 질문"); question.press("Enter")
        expect(question).to_have_value("충돌 질문")
        expect(page.locator('.chat-history-feedback')).to_have_text("다른 기기에서 변경되었습니다.")
        assert all(m["content"] != "충돌 질문" for c in conversations.values() for m in c["messages"])
        page.screenshot(path=str(tmp_path / "web-history.png"), full_page=True)

        # A 401 from any API returns to login without deleting server history.
        mode["expired"] = True
        page.reload()
        page.get_by_role("button", name="AI 챗봇", exact=True).click()
        expect(page.get_by_role("heading", name="학교 계정 로그인")).to_be_visible()
        assert len(conversations) == 2
        assert not failures, failures
        browser.close()
