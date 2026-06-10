# FastAPI Core (증분 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streamlit→FastAPI 마이그레이션의 첫 골격 — AsyncConnectionPool + `/api/health`(liveness) + `/api/chat`(비스트림, 기존 `GRAPH` 재사용)을 추가한다. RAG/`db` 로직은 수정하지 않는다.

**Architecture:** `SERVER/api/`에 얇은 웹 레이어를 신규로 둔다. `db/pool.py`가 풀(min_size=0 → 기동 시 DB 불필요, 클라우드 콜드스타트·테스트 친화)을 생성하고 lifespan이 open/close. `/api/chat`은 sync `GRAPH.invoke`를 `anyio.to_thread`로 감싸 이벤트루프 블로킹을 피하고, 결과 dict를 dart 계약의 flat 키로 매핑한다.

**Tech Stack:** FastAPI, uvicorn, Pydantic v2, psycopg_pool(AsyncConnectionPool), pgvector(register_vector_async), anyio, pytest + Starlette TestClient.

**전제(설계문서 `docs/superpowers/specs/2026-06-05-fastapi-migration-architecture-design.md`):**
- `APP/`(Flutter) 비수정. `api_service.dart`는 고정 계약. 응답은 flat 키, 에러는 `{"detail":"문자열"}`.
- 라이브 트리 = `SERVER/`. `core/` 재도입 금지. 프로바이더 하드코딩 금지.
- 이 증분 비범위: SSE 스트림, JWT, notices/search/portal, 워커, migrations — 후속 증분.

**테스트 실행 규약:** 모든 pytest는 **`SERVER/` 디렉터리에서 venv로** 실행한다(`cd SERVER && ../.venv/bin/python -m pytest ...`). `python -m`이 cwd(`SERVER`)를 sys.path에 올려 `retrieval.graph`·`api.main` 같은 top-level import가 해결된다.

---

## File Structure

- Create `SERVER/db/pool.py` — AsyncConnectionPool + register_vector configure (풀 1책임).
- Create `SERVER/api/__init__.py` — 빈 패키지 마커.
- Create `SERVER/api/main.py` — FastAPI 앱 + lifespan(pool open/close) + 라우터 등록.
- Create `SERVER/api/routers/__init__.py` — 빈 마커.
- Create `SERVER/api/routers/health.py` — `GET /health` liveness.
- Create `SERVER/api/routers/chat.py` — `POST /chat`, GRAPH 호출 + flat 키 매핑.
- Create `SERVER/api/schemas/__init__.py` — 빈 마커.
- Create `SERVER/api/schemas/chat.py` — `ChatRequest`/`ChatResponse`(dart 계약 1:1).
- Create `SERVER/tests/test_db_pool.py`, `SERVER/tests/test_api_health.py`, `SERVER/tests/test_api_chat.py`.
- Modify `SERVER/requirements.txt` — `fastapi`, `uvicorn[standard]` 추가(유일한 기존파일 변경).

---

## Task 0: 이슈 + 브랜치 (CLAUDE.md 5.2 work-start)

**선행: 사용자 "go" 후 실행.** `gh` 인증 필요.

- [ ] **Step 1: 이슈 생성**

```bash
gh issue create \
  --title "feat(api): FastAPI 코어 + DB 커넥션 풀 + /api/health·/api/chat 비스트림" \
  --body "배경: Streamlit→FastAPI 마이그레이션 증분1. 설계문서 docs/superpowers/specs/2026-06-05-fastapi-migration-architecture-design.md 참조.

범위: SERVER/api/ 웹 레이어 신규 + db/pool.py(AsyncConnectionPool, register_vector 풀 등록). /api/health(liveness), /api/chat(기존 GRAPH 재사용, 응답 flat 키). RAG/db 로직 비수정.
비범위: SSE 스트림, JWT, notices/search/portal, 워커, migrations.
검증: curl /api/health 200 / /api/chat 기존과 동일 답변(회귀 없음) / pg_stat_activity 커넥션 누수 없음."
```

기록: 출력된 이슈번호를 `<ISSUE>`로 둔다.

- [ ] **Step 2: base 브랜치 동기화 후 브랜치 생성**

```bash
git branch --show-current        # 기대: dev (현재 base)
git fetch && git pull
git switch -c feat/<ISSUE>-fastapi-core
```

Expected: `feat/<ISSUE>-fastapi-core` 브랜치로 전환.

---

## Task 1: 의존성 추가

**Files:**
- Modify: `SERVER/requirements.txt`

- [ ] **Step 1: requirements.txt에 fastapi/uvicorn 추가**

`SERVER/requirements.txt` 상단(psycopg 줄 근처)에 두 줄 추가:

```
fastapi
uvicorn[standard]
```

- [ ] **Step 2: venv에 설치**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant
.venv/bin/python -m pip install fastapi "uvicorn[standard]"
```
Expected: `Successfully installed fastapi-... starlette-... uvicorn-...`

- [ ] **Step 3: import 확인**

Run:
```bash
.venv/bin/python -c "import fastapi, uvicorn, httpx; print('deps ok')"
```
Expected: `deps ok`

- [ ] **Step 4: Commit**

```bash
git add SERVER/requirements.txt
git commit -m "build(api): FastAPI·uvicorn 의존성 추가"
```

---

## Task 2: DB 커넥션 풀 (`db/pool.py`)

**Files:**
- Create: `SERVER/db/pool.py`
- Test: `SERVER/tests/test_db_pool.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `SERVER/tests/test_db_pool.py`:

```python
from psycopg_pool import AsyncConnectionPool
from db.pool import pool


def test_pool_is_async_and_lazy():
    # min_size=0 → 기동 시 DB 연결 강제 안 함(콜드스타트·테스트 친화)
    assert isinstance(pool, AsyncConnectionPool)
    assert pool.min_size == 0
    assert pool.max_size >= 1
```

- [ ] **Step 2: 실패 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_db_pool.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'db.pool'`

- [ ] **Step 3: 최소 구현**

Create `SERVER/db/pool.py`:

```python
"""FastAPI용 비동기 커넥션 풀.

- min_size=0: 기동 시 DB 연결을 강제하지 않음(클라우드 콜드스타트·테스트 친화).
  풀은 첫 요청에서 연결을 채운다.
- configure: 풀이 만드는 모든 커넥션에 pgvector 어댑터를 1회 등록.
"""
import os

from psycopg_pool import AsyncConnectionPool
from pgvector.psycopg import register_vector_async

from db.schema import DB_URL


async def _configure(conn):
    await register_vector_async(conn)


pool = AsyncConnectionPool(
    conninfo=DB_URL,
    open=False,
    min_size=0,
    max_size=int(os.getenv("DB_POOL_MAX", "10")),
    configure=_configure,
)
```

- [ ] **Step 4: 통과 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_db_pool.py -v
```
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add SERVER/db/pool.py SERVER/tests/test_db_pool.py
git commit -m "feat(api): AsyncConnectionPool + pgvector 풀레벨 등록"
```

---

## Task 3: FastAPI 앱 + `/api/health`

**Files:**
- Create: `SERVER/api/__init__.py`, `SERVER/api/routers/__init__.py`, `SERVER/api/routers/health.py`, `SERVER/api/main.py`
- Test: `SERVER/tests/test_api_health.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `SERVER/tests/test_api_health.py`:

```python
from fastapi.testclient import TestClient

from api.main import app


def test_health_returns_ok():
    # TestClient context가 lifespan(pool open/close)을 실행한다.
    # min_size=0이라 DB 없이도 기동 성공해야 한다.
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: 실패 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_api_health.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 3: 패키지 마커 생성**

Create `SERVER/api/__init__.py` (빈 파일):

```python
```

Create `SERVER/api/routers/__init__.py` (빈 파일):

```python
```

- [ ] **Step 4: health 라우터 구현**

Create `SERVER/api/routers/health.py`:

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness 체크. dart는 HTTP 200만 본다(DB 의존 없음)."""
    return {"status": "ok"}
```

- [ ] **Step 5: 앱 + lifespan 구현**

Create `SERVER/api/main.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from db.pool import pool
from api.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="KNU AI Assistant API", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
```

- [ ] **Step 6: 통과 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_api_health.py -v
```
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
git add SERVER/api/__init__.py SERVER/api/routers/__init__.py SERVER/api/routers/health.py SERVER/api/main.py SERVER/tests/test_api_health.py
git commit -m "feat(api): FastAPI 앱 + lifespan 풀 관리 + /api/health"
```

---

## Task 4: `/api/chat` 스키마 + 라우터

**Files:**
- Create: `SERVER/api/schemas/__init__.py`, `SERVER/api/schemas/chat.py`, `SERVER/api/routers/chat.py`
- Modify: `SERVER/api/main.py` (라우터 등록 1줄)
- Test: `SERVER/tests/test_api_chat.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `SERVER/tests/test_api_chat.py`:

```python
from fastapi.testclient import TestClient

from api.main import app


def test_chat_maps_graph_result_to_flat_keys(monkeypatch):
    """GRAPH 결과 dict를 dart 계약 flat 키로 매핑하는지 검증.
    실제 GRAPH(DB·LLM 호출) 대신 가짜로 대체 — 매핑 로직만 테스트한다.
    """
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
    # GRAPH가 안 준 키는 null로 존재(dart Optional 대응)
    assert body["verifier_note"] is None


def test_chat_defaults_when_keys_missing(monkeypatch):
    """precise 경로가 일부 키만 줄 때 안전한 기본값."""
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
```

- [ ] **Step 2: 실패 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_api_chat.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routers.chat'`

- [ ] **Step 3: 스키마 구현**

Create `SERVER/api/schemas/__init__.py` (빈 파일):

```python
```

Create `SERVER/api/schemas/chat.py`:

```python
from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    major: Optional[str] = None


class ChatResponse(BaseModel):
    # api_service.dart ChatResult와 1:1 (flat 키). 없는 값은 null.
    answer: str
    grounded: Optional[bool] = None
    fidelity: Optional[float] = None
    verifier_note: Optional[str] = None
    categories: List[str] = []
    expanded_query: Optional[str] = None
```

- [ ] **Step 4: chat 라우터 구현**

Create `SERVER/api/routers/chat.py`:

```python
import anyio
from fastapi import APIRouter

from retrieval.graph import GRAPH
from api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


def _invoke_graph(question: str, major: str | None) -> dict:
    # GRAPH는 sync 제너레이터/그래프. 별도 스레드에서 호출해 이벤트루프 비블로킹.
    return GRAPH.invoke({"question": question, "major": major})


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    state = await anyio.to_thread.run_sync(_invoke_graph, req.question, req.major)
    # categories는 ChatState에서 enum일 수 있음 → 문자열로 정규화(dart는 string 배열).
    categories = [getattr(c, "value", c) for c in (state.get("categories") or [])]
    return ChatResponse(
        answer=state.get("answer", ""),
        grounded=state.get("grounded"),
        fidelity=state.get("fidelity"),
        verifier_note=state.get("verifier_note"),
        categories=categories,
        expanded_query=state.get("expanded_query"),
    )
```

- [ ] **Step 5: main.py에 chat 라우터 등록**

Modify `SERVER/api/main.py` — import 줄과 include 줄에 `chat` 추가:

```python
from api.routers import health, chat
```
```python
app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
```

- [ ] **Step 6: 통과 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_api_chat.py -v
```
Expected: PASS (2 passed)

- [ ] **Step 7: 전체 테스트 통과 확인**

Run:
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m pytest tests/test_db_pool.py tests/test_api_health.py tests/test_api_chat.py -v
```
Expected: PASS (4 passed)

- [ ] **Step 8: Commit**

```bash
git add SERVER/api/schemas/__init__.py SERVER/api/schemas/chat.py SERVER/api/routers/chat.py SERVER/api/main.py SERVER/tests/test_api_chat.py
git commit -m "feat(api): /api/chat 비스트림 — GRAPH 재사용 + flat 키 매핑"
```

---

## Task 5: 실서버 회귀 검증 (수동, DB+LLM 필요)

**Files:** 없음(검증 전용). 설계문서 Verification 절 수행.

- [ ] **Step 1: API 서버 기동**

Run (DB·LLM env가 `.env`에 설정된 상태에서):
```bash
cd /Users/iseung-won/knu_ai_assistant/SERVER
../.venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
Expected: `Uvicorn running on http://0.0.0.0:8000`, lifespan 에러 없음.

- [ ] **Step 2: health 확인**

Run (다른 터미널):
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/health
```
Expected: `200`

- [ ] **Step 3: chat 회귀 — 기존 GRAPH와 동일 답변**

Run:
```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"장학금 신청 언제야","major":"전자공학과"}' | python3 -m json.tool
```
Expected: `answer` 등 **flat 키** 포함 JSON. 답변 내용이 기존 Streamlit GRAPH 결과와 동등(회귀 없음).

- [ ] **Step 4: 커넥션 누수 점검**

Step 3을 5회 반복 호출 후:
```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();"
```
Expected: 커넥션 수가 max(10) 이하에서 안정(반복 호출 후에도 단조 증가/누수 없음).

> 참고: 이 증분의 `/api/chat`은 기존 `GRAPH` 내부의 단발 `psycopg.connect`를 그대로 탄다(풀 미사용). 풀의 실효 이득은 후속 "db 읽기경로 async 포팅" 증분부터. 따라서 Step 4 누수 점검은 GRAPH 내부 연결이 정상 종료되는지 확인하는 의미.

---

## Self-Review (작성자 체크)

- **Spec coverage:** §3 구조(api/, core 없음) ✓ / §4 풀+register_vector ✓ / §6 chat flat 키·`{"detail"}` 에러는 FastAPI 기본 유지 ✓ / D12 임베딩 미수정(이 증분은 임베딩 경로 무관) ✓ / 비범위(SSE·JWT·notices·워커·migrations) 제외 명시 ✓.
- **Placeholder scan:** `<ISSUE>`는 Task 0의 런타임 산출값(이슈번호) — 코드 placeholder 아님. 그 외 모든 코드 스텝은 완전 코드 포함.
- **Type consistency:** `ChatRequest/ChatResponse` 필드명이 Task 4 라우터·테스트와 일치. `pool.min_size`/`max_size` 속성 Task 2 테스트와 일치. `GRAPH.invoke` 시그니처 Task 4·테스트 일치.
- **DB 비의존 테스트:** pool min_size=0 + health DB 무의존 + chat은 GRAPH monkeypatch → Task 1~4는 DB 없이 green. 실DB 회귀는 Task 5(수동)로 분리.
