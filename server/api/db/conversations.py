"""Account-scoped snapshots with optimistic concurrency and idempotent import."""
from contextlib import asynccontextmanager
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg.errors import LockNotAvailable
from psycopg.types.json import Jsonb

from db.pool import pool


class ConversationMissing(LookupError):
    pass


class ConversationConflict(ValueError):
    pass


_COLUMNS = "id,title,source,revision,created_at,updated_at"


def _record(row, *, messages=False):
    result = dict(zip(("id", "title", "source", "revision", "created_at", "updated_at"), row[:6]))
    if messages:
        result["messages"] = row[6]
    return result


async def list_conversations(student_id, limit, cursor=None):
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            f"SELECT {_COLUMNS} FROM student_chat_conversation "
            "WHERE student_id=%s AND (%s::timestamptz IS NULL OR (updated_at,id)<(%s::timestamptz,%s::uuid)) "
            "ORDER BY updated_at DESC,id DESC LIMIT %s",
            (student_id, cursor[0] if cursor else None, cursor[0] if cursor else None,
             cursor[1] if cursor else None, limit + 1),
        )).fetchall()
    return [_record(row) for row in rows]


async def get_conversation(student_id, identity):
    async with pool.connection() as conn:
        row = await (await conn.execute(
            f"SELECT {_COLUMNS},messages FROM student_chat_conversation WHERE student_id=%s AND id=%s",
            (student_id, identity),
        )).fetchone()
    if row is None:
        raise ConversationMissing()
    return _record(row, messages=True)


async def search_conversations(student_id, query, limit=5):
    async with pool.connection() as conn:
        rows = await (await conn.execute(
            f"SELECT {_COLUMNS} FROM student_chat_conversation WHERE student_id=%s "
            "AND strpos(lower(title || ' ' || messages::text),lower(%s))>0 "
            "ORDER BY updated_at DESC,id DESC LIMIT %s", (student_id, query, limit),
        )).fetchall()
    return [_record(row) for row in rows]


async def create_conversation(student_id, body):
    identity = body.id or uuid4()
    messages = [message.model_dump() for message in body.messages]
    async with pool.connection() as conn:
        row = await (await conn.execute(
            f"INSERT INTO student_chat_conversation(id,student_id,title,source,messages) "
            f"VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING {_COLUMNS},messages",
            (identity, student_id, body.title, body.source, Jsonb(messages)),
        )).fetchone()
        if row is None:
            # Replaying an unknown-outcome create never overwrites a newer snapshot.
            row = await (await conn.execute(
                f"SELECT {_COLUMNS},messages FROM student_chat_conversation WHERE student_id=%s AND id=%s",
                (student_id, identity),
            )).fetchone()
            if row is None or row[1] != body.title or row[2] != body.source or row[6] != messages:
                raise ConversationConflict("이미 저장된 대화입니다. 기록을 새로 불러와주세요.")
    return _record(row, messages=True)


async def update_conversation(student_id, identity, body):
    async with pool.connection() as conn:
        row = await (await conn.execute(
            f"UPDATE student_chat_conversation SET title=%s,source=%s,messages=%s,"
            f"revision=revision+1,updated_at=now(),context_state=NULL,last_request_id=NULL WHERE student_id=%s AND id=%s AND revision=%s RETURNING {_COLUMNS},messages",
            (body.title, body.source, Jsonb([m.model_dump() for m in body.messages]), student_id, identity, body.revision),
        )).fetchone()
        if row is None:
            existing = await (await conn.execute(
                "SELECT 1 FROM student_chat_conversation WHERE student_id=%s AND id=%s", (student_id, identity),
            )).fetchone()
            if existing is None:
                raise ConversationMissing()
            raise ConversationConflict("다른 기기에서 대화가 변경되었습니다. 새로 불러온 뒤 이어서 대화해주세요.")
    return _record(row, messages=True)


async def delete_conversation(student_id, identity, revision):
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "DELETE FROM student_chat_conversation WHERE student_id=%s AND id=%s AND revision=%s RETURNING id",
            (student_id, identity, revision),
        )).fetchone()
        if row is None:
            existing = await (await conn.execute(
                "SELECT 1 FROM student_chat_conversation WHERE student_id=%s AND id=%s", (student_id, identity),
            )).fetchone()
            if existing is not None:
                raise ConversationConflict("다른 기기에서 변경된 기록입니다. 새로 불러온 뒤 삭제해주세요.")
            raise ConversationMissing()


async def import_conversations(student_id, items):
    saved = []
    async with pool.connection() as conn:
        for body in items:
            identity = uuid5(NAMESPACE_URL, f"knu-pick:{student_id}:{body.legacy_key}")
            await conn.execute(
                "INSERT INTO student_chat_conversation(id,student_id,title,source,messages,legacy_key) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(student_id,legacy_key) DO NOTHING",
                (identity, student_id, body.title, body.source,
                 Jsonb([m.model_dump() for m in body.messages]), body.legacy_key),
            )
            row = await (await conn.execute(
                f"SELECT {_COLUMNS},messages FROM student_chat_conversation WHERE student_id=%s AND legacy_key=%s",
                (student_id, body.legacy_key),
            )).fetchone()
            saved.append(_record(row, messages=True))
    return saved


class ConversationTurn:
    def __init__(self, conn, student_id, row, request):
        self.conn, self.student_id, self.request = conn, student_id, request
        self.conversation = _record(row, messages=True)
        self.context_state = row[7]
        self.replayed = row[8] == request.request_id
        if self.replayed:
            messages = self.conversation["messages"]
            if (len(messages) < 2 or messages[-2] != {"role": "user", "content": request.question}
                    or self.conversation["source"] != request.source):
                raise ConversationConflict("같은 요청 ID에 다른 질문을 사용할 수 없습니다.")
            self.answer = messages[-1]["content"]
        elif self.conversation["revision"] != (request.revision or 1):
            raise ConversationConflict("다른 기기에서 대화가 변경되었습니다. 대화를 다시 열어주세요.")

    async def finish(self, answer, state):
        messages = self.conversation["messages"] + [
            {"role": "user", "content": self.request.question}, {"role": "assistant", "content": answer}]
        if len(messages) > 10000 or sum(len(m["content"]) for m in messages) > 1000000:
            raise ConversationConflict("대화 원본의 저장 한도에 도달했습니다. 새 대화를 시작해주세요. 기존 기록은 유지됩니다.")
        first = next((m["content"] for m in messages if m["role"] == "user"), "새 대화")
        row = await (await self.conn.execute(
            f"UPDATE student_chat_conversation SET title=%s,source=%s,messages=%s,context_state=%s,"
            f"last_request_id=%s,revision=revision+1,updated_at=now() WHERE student_id=%s AND id=%s RETURNING {_COLUMNS},messages",
            (self.conversation["title"] if self.conversation["messages"] else first[:100], self.request.source,
             Jsonb(messages), Jsonb(state) if state else None, self.request.request_id,
             self.student_id, self.conversation["id"]),
        )).fetchone()
        self.conversation = _record(row, messages=True)


@asynccontextmanager
async def conversation_turn(student_id, request):
    # A DB lock fences API workers and other devices, not just this Python process.
    # It is released on success, failure, cancellation, and API process death.
    try:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute("SET LOCAL lock_timeout = '250ms'")
            if request.revision == 0:
                await conn.execute(
                    "INSERT INTO student_chat_conversation(id,student_id,title,source) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (request.conversation_id, student_id, request.question[:100], request.source),
                )
            row = await (await conn.execute(
                f"SELECT {_COLUMNS},messages,context_state,last_request_id FROM student_chat_conversation "
                "WHERE student_id=%s AND id=%s FOR UPDATE NOWAIT", (student_id, request.conversation_id),
            )).fetchone()
            if row is None:
                raise ConversationMissing()
            if request.revision == 0 and row[6] and row[8] != request.request_id:
                raise ConversationConflict("이미 저장된 대화입니다. 대화를 다시 열어주세요.")
            yield ConversationTurn(conn, student_id, row, request)
    except LockNotAvailable:
        raise ConversationConflict("다른 기기에서 이 대화의 답변을 생성하고 있습니다. 잠시 후 다시 열어주세요.") from None
