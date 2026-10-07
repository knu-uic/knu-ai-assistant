import asyncio
from uuid import uuid4

from interfaces.http.web.history_tools import TOOLS
from interfaces.mcp.server import _MCP_PRINCIPAL
from db import conversations


def test_history_tools_require_student_and_scope_search(monkeypatch):
    seen=[]
    async def search(student,query,limit):
        seen.append((student,query,limit)); return []
    monkeypatch.setattr(conversations,"search_conversations",search)
    async def scenario():
        anonymous=await TOOLS[0].run({"query":"장학금"})
        assert "error" in anonymous.structured_content
        token=_MCP_PRINCIPAL.set("portal:20260001")
        try:
            result=await TOOLS[0].run({"query":"장학금","limit":3})
            assert result.structured_content=={"reference_only":True,"items":[]}
        finally: _MCP_PRINCIPAL.reset(token)
    asyncio.run(scenario())
    assert seen==[("20260001","장학금",3)]


def test_history_read_preserves_long_original_and_hides_foreign_records(monkeypatch):
    original="가"*20000; identity=uuid4()
    async def get(student,key):
        if student!="20260001": raise conversations.ConversationMissing()
        return {"id":identity,"messages":[{"role":"user","content":original}]}
    monkeypatch.setattr(conversations,"get_conversation",get)
    async def scenario():
        token=_MCP_PRINCIPAL.set("portal:20260001")
        try:
            first=(await TOOLS[1].run({"conversation_id":str(identity),"max_chars":10000})).structured_content
            second=(await TOOLS[1].run({"conversation_id":str(identity),"char_offset":10000})).structured_content
            assert first["content"]+second["content"]==original
            assert first["next_char_offset"]==10000 and second["next_char_offset"] is None
        finally: _MCP_PRINCIPAL.reset(token)
        token=_MCP_PRINCIPAL.set("portal:20260002")
        try:
            assert "error" in (await TOOLS[1].run({"conversation_id":str(identity)})).structured_content
        finally: _MCP_PRINCIPAL.reset(token)
    asyncio.run(scenario())
