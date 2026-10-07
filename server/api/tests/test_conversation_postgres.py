"""Opt-in integration tests against a disposable PostgreSQL, never the real DB."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import httpx
from psycopg import sql
from psycopg_pool import AsyncConnectionPool
import pytest

from db import conversations as repository
from interfaces.http.schemas.conversations import ConversationCreate, ConversationUpdate, LegacyConversation
from interfaces.http.schemas.chat import ChatRequest

DSN=os.environ.get("KNU_CONTEXT_TEST_DSN")
pytestmark=pytest.mark.skipif(not DSN,reason="Disposable KNU_CONTEXT_TEST_DSN required")


def test_real_sql_isolation_revision_import_turn_atomicity_and_locks(monkeypatch):
    async def scenario():
        schema="context_test_"+uuid4().hex
        admin=await psycopg.AsyncConnection.connect(DSN,autocommit=True)
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        async def configure(conn):
            await conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            await conn.commit()
        pool=AsyncConnectionPool(DSN,min_size=1,max_size=4,open=False,configure=configure)
        try:
            await pool.open(); await pool.wait()
            monkeypatch.setattr(repository,"pool",pool)
            async with pool.connection() as conn:
                await conn.execute("CREATE TABLE users(student_id varchar(20) PRIMARY KEY)")
                await conn.execute("INSERT INTO users VALUES ('a'),('b')")
                migrations=Path(__file__).resolve().parents[1]/"migrations"
                for name in ("018_student_chat_history.sql","019_student_chat_context.sql"):
                    await conn.execute((migrations/name).read_text())
            body=ConversationCreate(id=uuid4(),title="질문",messages=[{"role":"user","content":"원본"}])
            first=await repository.create_conversation("a",body)
            assert (await repository.create_conversation("a",body))["revision"]==1
            with pytest.raises(repository.ConversationMissing):
                await repository.get_conversation("b",body.id)
            with pytest.raises(repository.ConversationConflict):
                await repository.create_conversation("b",body)
            changed=ConversationUpdate(title="변경",revision=1,messages=[{"role":"user","content":"원본 변경"}])
            assert (await repository.update_conversation("a",body.id,changed))["revision"]==2
            with pytest.raises(repository.ConversationConflict):
                await repository.update_conversation("a",body.id,changed)
            with pytest.raises(repository.ConversationMissing):
                await repository.delete_conversation("b",body.id,2)
            legacy=LegacyConversation(legacy_key="old-browser-id",title="이전",messages=[{"role":"user","content":"이전 원본"}])
            imported=(await repository.import_conversations("a",[legacy]))[0]
            imported2=(await repository.import_conversations("a",[legacy]))[0]
            assert imported["id"]==imported2["id"]
            assert (await repository.import_conversations("b",[legacy]))[0]["id"]!=imported["id"]
            req=ChatRequest(question="이어가기",conversation_id=body.id,revision=2,request_id=uuid4())
            checkpoint={"summary":"요약","coveredMessageCount":1}
            async with repository.conversation_turn("a",req) as turn:
                assert turn.conversation["messages"][0]["content"]=="원본 변경"
                with pytest.raises(repository.ConversationConflict):
                    async with repository.conversation_turn("a",req):
                        pytest.fail("second writer entered")
                await turn.finish("답변",checkpoint)
            async with repository.conversation_turn("a",req) as turn:
                assert turn.replayed and turn.answer=="답변"
                assert turn.context_state==checkpoint
            saved=await repository.get_conversation("a",body.id)
            assert saved["revision"]==3 and len(saved["messages"])==3
            fail=ChatRequest(question="실패",conversation_id=body.id,revision=3,request_id=uuid4())
            with pytest.raises(RuntimeError):
                async with repository.conversation_turn("a",fail) as turn:
                    await turn.finish("저장하면 안 되는 답변",None)
                    raise RuntimeError("provider/storage failure")
            assert await repository.get_conversation("a",body.id)==saved
            new=ChatRequest(question="첫 질문",conversation_id=uuid4(),revision=0,request_id=uuid4())
            async with repository.conversation_turn("a",new) as turn:
                await turn.finish("첫 답변",None)
            async with repository.conversation_turn("a",new) as turn:
                assert turn.replayed
            with pytest.raises(repository.ConversationMissing):
                async with repository.conversation_turn("b",new):
                    pytest.fail("foreign history accessed")
            await repository.delete_conversation("a",body.id,3)
            with pytest.raises(repository.ConversationMissing):
                await repository.get_conversation("a",body.id)
            # Real KNU -> real Node engine -> mocked provider -> real PostgreSQL,
            # including compaction persisted and reused on the next device/turn.
            import interfaces.http.web.chat as chat
            from api.chat_context import CURRENT_TURN
            source_messages=[{"role":"user" if i%2==0 else "assistant","content":"가"*160} for i in range(40)]
            source_messages[0]["content"]="전공은 컴퓨터공학이고 장학금 안내를 원합니다."
            seeded=await repository.create_conversation("a",ConversationCreate(id=uuid4(),title="긴 대화",source="personal",messages=source_messages))
            summary_calls=[]; inference_inputs=[]
            async def account(student_id,account_id=None):
                return {"id":student_id,"provider":"google","model":"mock","secret":{"api_key":"test-only-"+student_id}}
            async def catalog():
                return [],{}
            def provider(request):
                payload=__import__('json').loads(request.content)
                messages=payload["messages"]
                if messages[0]["content"].startswith("Compress the conversation"):
                    summary_calls.append(messages)
                    text="학생의 전공은 컴퓨터공학이며 장학금 안내를 요청했습니다."
                else:
                    inference_inputs.append(messages)
                    text="컴퓨터공학 전공 학생의 장학금 안내입니다."
                return httpx.Response(200,json={"choices":[{"message":{"content":text},"finish_reason":"stop"}]})
            factory=httpx.AsyncClient
            monkeypatch.setattr(chat,"get_account",account)
            monkeypatch.setattr(chat,"_tool_catalog",catalog)
            monkeypatch.setattr(httpx,"AsyncClient",lambda *a,**kw: factory(*a,**{**kw,"transport":httpx.MockTransport(provider)}))
            monkeypatch.setenv("KNU_CHAT_CONTEXT_WINDOW","8192")
            request=ChatRequest(question="내 전공에 맞춰 알려줘",conversation_id=seeded["id"],revision=1,request_id=uuid4())
            result=await chat.generate_chat("a",request)
            assert result["conversation"]["revision"]==2
            assert len(result["conversation"]["messages"])==42
            assert result["context"]["compactionMode"]=="summary"
            assert len(summary_calls)==1
            assert "컴퓨터공학" in __import__('json').dumps(inference_inputs,ensure_ascii=False)
            assert CURRENT_TURN.get() is None
            # Retry after a lost response must not generate/bill a second answer.
            replay=await chat.generate_chat("a",request)
            assert replay["answer"]==result["answer"] and len(inference_inputs)==1
            next_request=ChatRequest(question="앞의 내용 계속",conversation_id=seeded["id"],revision=2,request_id=uuid4())
            again=await chat.generate_chat("a",next_request)
            assert again["conversation"]["revision"]==3
            assert len(summary_calls)==1
            assert len(again["conversation"]["messages"])==44
            assert await repository.search_conversations("a","컴퓨터공학")
            assert not await repository.search_conversations("b","컴퓨터공학")
        finally:
            await pool.close()
            await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await admin.close()
    asyncio.run(scenario())
