# 아키텍처 rev3 델타 — rev2(2026-06-05) 이후 변경 반영

> rev2(`2026-06-05-fastapi-migration-architecture-design.md`)를 대체하지 않는다.
> rev2를 기준으로 **무효화된 절 / 이미 끝난 작업 / 새로 생긴 리스크 / 수정된 증분 순서**만 기록한다.
> 충돌 시 이 문서가 우선.

## 1. 무효화된 결정 (사용자 결정 2026-06-09~10)

### 1.1 §1 "채팅 공개(B5)" → 폐기. 전 API 자체 로그인 보호

- rev2: `/api/chat`·`/api/notices`·`/api/search`는 공개 + IP 레이트리밋, JWT는 개인정보 엔드포인트만.
- **변경**: 사용자 결정으로 자체 계정(JWT) 인증을 chat/notices/search에 적용 (PR #95).
  공개 엔드포인트는 `/api/health`, `/api/auth/*`뿐.
- 근거: LLM 비용 무방비 차단이 UX 마찰보다 우선.

### 1.2 §1/§5 "JWT는 portal sync 완료 시 발급" → 폐기. 로그인으로 발급

- rev2: 비번 온디맨드 → sync job done 시 JWT(sub=student_id) 발급. job_id가 사실상 신원 토큰.
- **변경**: JWT는 `POST /api/auth/login`에서 발급, **sub=username** (student_id 아님).
  - `accounts` 테이블 신설 (username, bcrypt hash, student_id 예약 컬럼).
  - portal sync는 인증 *수단*이 아니라 로그인 후 쓰는 *기능*이 된다. job done 시 JWT 발급 대신 `accounts.student_id` 연결만 수행.
- rev2의 job_id 스크럽 경고는 **여전히 유효** (job_id로 타인 동기화 결과 조회 가능하므로 추측불가 토큰 + 로그 스크럽 유지).

### 1.3 §4 "24곳 async 포팅 = 최장 작업" → 강등. sync_pool로 해소

- rev2: psycopg.connect 24곳 전부 async 포팅 전까지 풀 이득 0 — 최장 작업.
- **변경**: `db/pool.py`에 `sync_pool`(ConnectionPool) 추가, users/documents/lms 23곳 교체 완료 (PR #94).
  connect-storm은 async 포팅 없이 이미 제거됨. 라우터는 sync 함수를 `anyio.to_thread`로 감싸는 현 패턴 유지.
- async 포팅은 "필수 마이그레이션"에서 "선택적 최적화"로 강등. 당분간 착수 안 함.

## 2. rev2 중 유효 — 그대로 진행

| 절 | 내용 | 상태 |
|---|---|---|
| §2 | dart flat 키 계약, `{"detail":"문자열"}` 에러 | 준수 중 |
| §3 | `api/` 얇은 웹 레이어, `core/` 재도입 금지, raw SQL | 준수 중 |
| §6 | SSE = thread+asyncio.Queue 브리지 (D11 함정) | 미착수, 설계 유효 |
| §6 | notices 키셋 페이지네이션 | 미착수, 유효 |
| §5/§8 | Arq+Redis 워커, 컨테이너 분리, 상시 워커 | 미착수, 유효 |
| §9 | LangSmith 단일 관측 + Sentry | 미착수, 유효 |
| D13 | raw SQL migrations 러너, 동적 분할 테이블은 제외(G2) | 미착수, 유효 |
| D12 | embed.py 위임 유지 (per-chunk embed_query — 배치 버그 메모리 참조) | 준수 중 |

## 3. 자체 로그인 전환으로 새로 생긴 리스크

1. **공개 signup = LLM 비용 구멍.** 누구나 가입하면 인증 보호가 무의미.
   배포 전 택1 필수: ① signup/login 레이트리밋(slowapi) ② 초대 코드 ③ 학교 메일 인증.
2. **IDOR 가드 수정 필요.** rev2 G1은 `JWT sub == path student_id` 비교 전제.
   이제 sub=username → `/api/user/{id}` 구현 시 **accounts에서 username→student_id 조회 후 비교**해야 함.
3. **장수 액세스 토큰.** 현재 TTL 30일, refresh 회전 없음. 학내 서비스 수준에선 허용,
   prod 공개 전 rev2 §1 토큰 관리(15~30분 + refresh)로 회귀 검토.
4. **accounts 테이블이 init_db로 들어감.** D13 러너 부재라 불가피했음.
   migrations 골격 도입 시 첫 마이그레이션에서 baseline 처리.

## 4. 수정된 증분 순서 (rev2 §산출물 교체)

1. ~~FastAPI 코어~~ ✅ (feat/89, health/chat/notices/search)
2. ~~sync 풀~~ ✅ (PR #94) / ~~자체 인증~~ ✅ (PR #95) / ~~EMBEDDING_DIM 검증~~ ✅ (PR #93)
3. **Flutter 로그인 연동** — login 호출, secure storage, Bearer 헤더, 401 처리
4. **레이트리밋** — slowapi: signup/login IP 기반 + chat 유저 기반 (리스크 1 해소)
5. **migrations 러너 골격** — 이후 스키마 변경 전부 이 위에서 (리스크 4 baseline 포함)
6. **SSE `/api/chat/stream`** — rev2 §6 설계 그대로
7. **notices 키셋 페이지네이션** — 인덱스는 migrations로
8. **portal sync Arq 잡 + 상시 워커** — done 시 student_id 연결 (1.2 변경 반영)
9. **`/api/user`·`/api/timetable`** — IDOR 가드는 username→student_id 매핑 경유 (리스크 2)
10. LangSmith/Sentry → CORS → React SPA

순서 근거: 인증이 이미 들어갔으므로 클라이언트 연동(3)과 비용 방어(4)가
인프라(5~8)보다 먼저. migrations(5)는 rev2 원칙대로 다음 스키마 변경(7,8,9) 전에.
