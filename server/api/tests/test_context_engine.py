import asyncio
import json
import os
import shutil

import pytest
from fastapi import HTTPException

from api.context_engine import run_engine

pytestmark = pytest.mark.skipif(not (os.environ.get("KNU_CONTEXT_NODE") or shutil.which("node")), reason="Node.js context runtime required")


def history(count=40, size=1000):
    return [{"id": str(i), "role": "user" if i % 2 == 0 else "assistant", "content": "가" * size} for i in range(count)]


def payload(messages, state=None, provider="student-a"):
    return {"type": "prepare", "session": {"messages": messages, "contextCompaction": state},
            "options": {"provider": provider, "model": "mock", "contextWindow": 8000}, "nativeSupported": True}


def test_shared_engine_keeps_more_than_twelve_messages_without_compaction():
    original = history(50, 5)
    result = asyncio.run(run_engine(payload(original)))
    assert result["history"] == [{"role": m["role"], "content": m["content"]} for m in original]
    assert not result["stateChanged"]


def test_native_fallback_semantic_checkpoint_resume_and_original_preservation():
    original = history()
    frozen = json.dumps(original)
    modes = []

    async def compact(frame):
        modes.append(frame["mode"])
        if frame["mode"] == "native":
            raise ValueError("unsupported")
        assert "NEW CONVERSATION TO COMPACT" in frame["transcript"]
        assert "estimatedTokens" in frame
        return {"mode": "summary", "summary": "전공은 컴퓨터공학이고 장학금 안내를 원함"}

    async def scenario():
        first = await run_engine(payload(original), compact)
        assert first["stateChanged"]
        assert first["state"]["mode"] == "summary"
        assert first["summary"]["content"].startswith("전공")
        assert len(first["history"]) < 12
        assert len(first["fallbackHistory"]) == 40
        resumed = await run_engine(payload(original, first["state"]), compact)
        assert not resumed["stateChanged"]
        assert resumed["summary"] == first["summary"]
        return first

    asyncio.run(scenario())
    assert modes == ["native", "summary"]
    assert json.dumps(original) == frozen


def test_failed_compaction_retains_every_message():
    async def broken(frame):
        raise RuntimeError("provider failure")

    result = asyncio.run(run_engine(payload(history()), broken))
    assert result["compactionFailed"]
    assert len(result["history"]) == 40
    assert result["state"] is None


def test_student_model_scope_changes_discard_old_checkpoint():
    async def compact(frame):
        return {"mode": "summary", "summary": "student A only"}

    async def scenario():
        first = await run_engine(payload(history()), compact)
        new = await run_engine(payload(history(2, 3), first["state"], provider="student-b"), compact)
        assert new["summary"] is None
        assert new["stats"]["compactedMessageCount"] == 0
    asyncio.run(scenario())


def test_missing_runtime_is_explicit_not_silent_history_truncation(monkeypatch):
    monkeypatch.setenv("KNU_CONTEXT_NODE", "/nonexistent/knu-test-node")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_engine(payload([])))
    assert exc.value.status_code == 503


def test_unexecutable_runtime_is_explicit(monkeypatch, tmp_path):
    invalid = tmp_path / "node"
    invalid.write_text("not executable")
    monkeypatch.setenv("KNU_CONTEXT_NODE", str(invalid))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_engine(payload([])))
    assert exc.value.status_code == 503


def test_parallel_compaction_callbacks_do_not_deadlock():
    async def compact(frame):
        await asyncio.sleep(0.01)
        return {"mode": "summary", "summary": "separate request"}
    async def scenario():
        result = await asyncio.wait_for(asyncio.gather(*(run_engine(payload(history(), provider=str(i)), compact) for i in range(8))), 15)
        assert all(r["stateChanged"] for r in result)
    asyncio.run(scenario())
