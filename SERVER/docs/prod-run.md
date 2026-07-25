# prod 배포 서버 실행 가이드

도커 컴포즈로 전체 스택을 한 번에 띄우는 배포용 실행법.
네이티브 개발 실행은 [dev-run.md](dev-run.md) 참고.

구성 파일: `SERVER/docker-compose.prod.yml` (개발용 `docker-compose.yml`과 별도).

## 서비스 구성

| 서비스 | 이미지/빌드 | 외부 노출 | 역할 |
|--------|-------------|-----------|------|
| db | pgvector/pgvector:pg16 | ❌ 내부 전용 | postgres + pgvector |
| redis | redis:7-alpine | ❌ 내부 전용 | 잡 큐 · LMS 세션 보관 |
| api | `Dockerfile.api` (슬림) | ❌ 내부 전용 | FastAPI |
| worker | `Dockerfile` (헤비, playwright·libreoffice) | ❌ 내부 전용 | arq — 동기화·공지 수집 |
| web | `../WEB/Dockerfile` (node 빌드 → caddy) | ✅ **80포트** | SPA 정적 서빙 + `/api/*` 프록시 |

**외부로 열리는 문은 web(80) 하나뿐.** db·redis·api·worker는 컨테이너 네트워크
(`bot_network`) 안에서만 통신한다. 그래서 api 검증은 호스트가 아니라 컨테이너 안에서 한다.

## 사전 준비: `.env`

`SERVER/.env`가 필요하다. compose가 `env_file`로 읽고, 일부만 도커용으로 덮어쓴다
(`RUNTIME_ENV=docker` → `DB_HOST=db`, `REDIS_URL=redis://redis:6379`).
없으면 `.env.example`를 복사해 채운다. 기본값 없어 **반드시 설정해야 하는 것**:

- `DB_PASSWORD` — postgres 비밀번호 (compose가 db·api·worker에 함께 주입)
- `AUTH_JWT_SECRET` — 로그인 토큰 서명 키
- `PORTAL_SYNC_ENC_KEY` — 포털 비번 전달용 Fernet 키
  (생성: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- `MCP_AUTH_TOKEN` — 내부 데모의 공지 근거 MCP Bearer token
  (생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- provider 키 — `EMBEDDING_PROVIDER`/`LLM_MODEL` 등 토글에 맞는 API 키
  (prod 기본 OpenAI: `OPENAI_API_KEY`)

> `.env`·`.secrets/`는 `.dockerignore`로 이미지에 안 들어간다. compose가 런타임에 주입.

## 띄우기

```bash
cd ~/knu_ai_assistant/SERVER

# 1. 빌드 + 전체 기동 (백그라운드)
docker compose -f docker-compose.prod.yml up -d --build

# 2. DB 마이그레이션 (1회 — 스키마는 부팅 시 자동 생성 안 됨)
docker compose -f docker-compose.prod.yml exec api python -m db.migrate

# 3. api 헬스체크 (컨테이너 안에서 — 호스트 포트 미노출)
docker compose -f docker-compose.prod.yml exec api curl -s localhost:8000/api/health
```

확인: 브라우저 `http://localhost` (80포트) 접속 → 로그인 → 공지/챗봇 동작하면 정상.

## 내부 MCP 공지 근거 조회

`/api/mcp`는 기존 web(80)의 `/api/*` 프록시를 통해서만 제공되는 내부 데모용
stateless Streamable HTTP MCP 경로다. `Authorization: Bearer $MCP_AUTH_TOKEN` 헤더가
없으면 요청은 거부된다. token을 tool 인자나 모델 대화에 넣지 않는다.

제공 도구는 `search_knu_notices`와 `get_knu_notice_detail` 두 개뿐이다. 서버는 공지
검색·상세 근거만 반환하며, 요청자 모델이 검색 반복과 최종 답변을 만든다.

```bash
cd ~/knu_ai_assistant/SERVER
../.venv/bin/python - <<'PY'
import asyncio
import os
from fastmcp import Client

async def main():
    async with Client("http://localhost/api/mcp", auth=os.environ["MCP_AUTH_TOKEN"]) as client:
        print([tool.name for tool in await client.list_tools()])
        print(await client.call_tool("search_knu_notices", {"query": "수강 철회", "limit": 3}))

asyncio.run(main())
PY
```

검색 결과의 `category`와 `url`로 `get_knu_notice_detail`을 호출해 본문과 출처 URL을
대조한다. 이 경로는 일반 공개 인증·사용량 보호가 추가되기 전까지 외부에 공개하지 않는다.

## 상태 · 로그

```bash
docker compose -f docker-compose.prod.yml ps           # 서비스 상태
docker compose -f docker-compose.prod.yml logs -f api     # api 로그 추적
docker compose -f docker-compose.prod.yml logs -f worker  # 동기화/수집 잡 로그
```

## 내리기

```bash
cd ~/knu_ai_assistant/SERVER

docker compose -f docker-compose.prod.yml down      # 컨테이너만 제거, 데이터(pgdata) 유지
docker compose -f docker-compose.prod.yml down -v   # ⚠️ pgdata 볼륨까지 삭제 (DB 초기화)
```

## 자주 걸리는 것

- **api/worker가 부팅에서 죽음** → `.env` 누락 또는 필수 env 미설정.
  `logs api`로 확인. db는 `healthcheck` 통과 후에 api가 뜨도록 `depends_on`이 잡혀있다.
- **로그인/조회는 되는데 검색·챗봇이 빈 결과** → 마이그레이션 안 돌았거나 데이터 미수집.
  `python -m db.migrate` 실행 여부 확인.
- **동기화(포털/LMS)가 큐에서 안 빠짐** → worker 컨테이너 상태 확인 (`ps`). redis도 필요.
- **이미지 재빌드가 안 먹음** → `up -d --build`로 다시. 캐시 문제면 `build --no-cache`.
- LMS 로그인 세션은 Redis에 저장되므로 worker에 `.secrets` 볼륨 마운트가 불필요하다.
