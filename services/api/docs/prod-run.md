# 공식 외부 호스팅 실행 가이드

도커 컴포즈로 전체 스택을 한 번에 띄우는 배포용 실행법.
네이티브 개발 실행은 [dev-run.md](dev-run.md) 참고.

구성 파일: `services/api/docker-compose.prod.yml` (개발용 `docker-compose.yml`과 별도).

## 서비스 구성

| 서비스 | 이미지/빌드 | 외부 노출 | 역할 |
|--------|-------------|-----------|------|
| db | pgvector/pgvector:pg16 | ❌ 내부 전용 | postgres + pgvector |
| redis | redis:7-alpine | ❌ 내부 전용 | 잡 큐 · LMS 세션 보관 |
| api | `Dockerfile.api` (슬림) | ❌ 내부 전용 | FastAPI |
| worker | `Dockerfile` (playwright·문서 구조 파서) | ❌ 내부 전용 | arq — 동기화·공지 수집 |
| migrate | `Dockerfile.api` | ❌ 내부 전용 | 배포마다 DB migration 적용 |
| web | `../../apps/web/Dockerfile` (node 빌드 → caddy) | ✅ **80/443포트** | TLS·SPA·`/api/*` 프록시 |

**외부로 열리는 문은 Caddy의 80/443뿐이다.** db·redis·api·worker는 컨테이너
네트워크 안에서만 통신한다. `/api/admin/*`는 Caddy에서 404로 차단하고,
일반 API와 MCP는 같은 HTTPS origin으로 제공한다.

## 사전 준비: `.env`

`services/api/.env.hosted.example`을 `.env`로 복사해 운영 값을 채운다. compose가
`env_file`로 읽고, 일부만 도커용으로 덮어쓴다
(`RUNTIME_ENV=docker` → `DB_HOST=db`, `REDIS_URL=redis://redis:6379`).
기본값 없이 **반드시 설정해야 하는 것**:

- `KNU_SITE_ADDRESS` — DNS가 이 서버를 가리키는 공식 도메인. 스킴 없이 입력
- `WEB_CORS_ORIGINS` — `https://<KNU_SITE_ADDRESS>`

- `DB_PASSWORD` — postgres 비밀번호 (compose가 db·api·worker에 함께 주입)
- `AUTH_JWT_SECRET` — 로그인 토큰 서명 키
- `PORTAL_SYNC_ENC_KEY` — 포털 비번 전달용 Fernet 키
  (생성: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- `MCP_AUTH_TOKEN` — 운영자 내부 점검용 token. 일반 사용자는 알거나 입력하지 않는다.
  (생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- provider 키 — `EMBEDDING_PROVIDER`/`LLM_MODEL` 등 토글에 맞는 API 키
  (prod 기본 OpenAI: `OPENAI_API_KEY`)

> `.env`·`.secrets/`는 `.dockerignore`로 이미지에 안 들어간다. compose가 런타임에 주입.

도메인의 A/AAAA 레코드를 서버로 연결하고 방화벽에서 TCP 80/443과 UDP 443만
허용한다. Caddy가 도메인을 확인한 뒤 TLS 인증서를 자동 발급·갱신한다.

## 띄우기

```bash
cd ~/knu-ai-assistant/services/api

# 1. 빌드 + 전체 기동 (백그라운드)
docker compose -f docker-compose.prod.yml up -d --build

# 2. 외부 HTTPS 헬스체크
curl -fsS "https://${KNU_SITE_ADDRESS}/api/health"
```

`migrate` 서비스가 성공한 뒤 API와 worker가 시작되고, API healthcheck가 통과한
뒤 Caddy가 기동한다. 브라우저에서 `https://<공식 도메인>`을 열어 확인한다.

## 외부 MCP 연결

`/api/mcp`는 두 인증 경로를 지원한다.

- 공식 진입점(`https://<공식 도메인>/api/mcp`)은 API로 그대로 프록시되며,
  Codmes가 포털 로그인으로 발급받은 사용자별 session token을 Bearer로 보낸다.
  일반 사용자는 별도 MCP token을 입력하지 않는다.
- 운영 점검은 서버 내부에서 직접 API 컨테이너를 호출하고 `MCP_AUTH_TOKEN`을
  Bearer로 전달한다. 이 토큰을 공개 URL이나 플러그인 manifest에 넣지 않는다.

두 경로 모두 tool 인자나 모델 대화에 token을 넣지 않는다. 사용자 경로는 JWT
subject의 학번을 기준으로 `RATE_LIMIT_MCP`를 적용하므로 같은 학번의 여러 기기는
한도를 공유한다. 기본값은 `60/minute`다.

포털 session token은 만료일 대신 Redis의 활성 session record로 검증한다. Redis는
AOF와 `redisdata` volume을 사용해 재시작 후에도 session을 유지한다. 사용자가
로그아웃하면 현재 session record만 제거하며 다른 기기의 session은 유지한다.

KNU MCP는 다음 도구를 제공한다.

- `knu_list_notices`: 구조화된 메타데이터로 목록·개수·신청 상태를 조회하는 Scan 도구
- `knu_search_notice_details`: 구체적인 자격·절차·제출 서류를 vector 검색과
  reranking으로 찾는 Deep 도구
- `knu_get_notice_detail`: URL로 보존 중인 공지 원문을 조회하는 도구
- `knu_get_portal_academic_data`: 로그인 사용자의 학적·시간표·성적·졸업학점 조회
- `knu_list_lms_tasks`: 로그인 사용자의 LMS 학습활동 조회
- `knu_list_lms_courses`: 로그인 사용자의 LMS 과목 조회
- `knu_get_student_profile`: 로그인 계정의 학적정보 조회

각 `tools/list` 항목은 실제 JSON input schema와 읽기 전용 annotation을 제공한다.
또한 선택적인 `com.codmes/tool` metadata로 안정적인 공개 이름과
`knu.notices`, `knu.lms`, `knu.portal`, `knu.account` 계층 그룹을 제공한다.
Codmes가 아닌 표준 MCP client는 이 확장 metadata를 무시하고 같은 도구를 그대로
사용할 수 있다. Codmes의 Surface 범위·credential·승인 정책은 KNU plugin이 계속
소유하므로 MCP metadata가 client 보안 정책을 낮추지는 못한다.

Scan/Deep 선택과 시간 범위는 Codmes 대화 모델이 질문 의미를 보고 결정한다. KNU
MCP 내부에는 질문 키워드 router나 별도의 LLM 호출이 없다. 도구 결과는 사람이 읽을
수 있는 `content`와 기계가 그대로 이용할 수 있는 `structuredContent`를 함께
반환하며, 요청자 모델이 근거 URL을 인용해 최종 답변을 만든다.

사용자 session으로 호출하면 KNU MCP는 학번에 연결된 학적정보를 자동으로 읽는다.
도구의 `department`를 생략한 기본 호출은 학교 공통 게시판과 사용자 학과 게시판만
조회하며, Scan은 학년도 함께 적용한다. 다른 학과를 명시적으로 묻는 경우에만
Codmes 모델이 `department`를 전달해 이 기본 범위를 바꾼다. 이 필터는 임베딩 검색
전에 적용되므로 다른 학과 문서가 높은 유사도만으로 Deep 결과에 섞이지 않는다.

`department`는 MCP JSON Schema에 등록된 학과 enum만 허용한다. 기존
클라이언트가 `공주대`, `공주대학교`, `KNU`처럼 학교명을 전달하면 서버가
생략된 필터로 정규화하며, 그 외의 알 수 없는 학과는 검증 오류로 거부한다.
`grade`의 공개 스키마는 1–4 정수 enum이다. 소형 모델이 `2학년`처럼 단위를
붙여 보내는 경우에만 입력 경계에서 `2`로 복구하며, 범위 밖 값은 그대로 거부한다.

```bash
cd ~/knu-ai-assistant/services/api
../../.venv/bin/python - <<'PY'
import asyncio
from fastmcp import Client

async def main():
    async with Client(
        "https://knu.example.org/api/mcp",
        auth="<portal-login으로 발급된 사용자 token>",
    ) as client:
        print([tool.name for tool in await client.list_tools()])
        print(await client.call_tool(
            "knu_list_notices",
            {"category": "수강", "status": "open"},
        ))
        print(await client.call_tool(
            "knu_search_notice_details",
            {"query": "수강 철회 절차와 제출 서류", "category": "수강"},
        ))

asyncio.run(main())
PY
```

예시 도메인은 실제 `KNU_SITE_ADDRESS`로 교체한다. 검색 결과의 `url`로
`knu_get_notice_detail`을 호출해 본문과 출처 URL을 대조한다.

## 상태 · 로그

```bash
docker compose -f docker-compose.prod.yml ps           # 서비스 상태
docker compose -f docker-compose.prod.yml logs -f api     # api 로그 추적
docker compose -f docker-compose.prod.yml logs -f worker  # 동기화/수집 잡 로그
```

## 내리기

```bash
cd ~/knu-ai-assistant/services/api

docker compose -f docker-compose.prod.yml down      # 컨테이너만 제거, 데이터(pgdata) 유지
docker compose -f docker-compose.prod.yml down -v   # ⚠️ pgdata 볼륨까지 삭제 (DB 초기화)
```

## 자주 걸리는 것

- **api/worker가 부팅에서 죽음** → `.env` 누락 또는 필수 env 미설정.
  `logs api`로 확인. db는 `healthcheck` 통과 후에 api가 뜨도록 `depends_on`이 잡혀있다.
- **Caddy가 인증서를 발급하지 못함** → DNS A/AAAA, 방화벽 80/443,
  `KNU_SITE_ADDRESS`에 스킴이나 경로를 넣지 않았는지 확인한다.
- **로그인/조회는 되는데 검색·챗봇이 빈 결과** → 마이그레이션 안 돌았거나 데이터 미수집.
  `python -m db.migrate` 실행 여부 확인.
- **동기화(포털/LMS)가 큐에서 안 빠짐** → worker 컨테이너 상태 확인 (`ps`). redis도 필요.
- **이미지 재빌드가 안 먹음** → `up -d --build`로 다시. 캐시 문제면 `build --no-cache`.
- LMS 로그인 세션은 Redis에 저장되므로 worker에 `.secrets` 볼륨 마운트가 불필요하다.
