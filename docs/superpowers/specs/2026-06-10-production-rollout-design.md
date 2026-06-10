# KNU AI Assistant — 교내 실사용 배포 설계 (rollout plan)

> 전제 문서: rev2(`2026-06-05-fastapi-migration-architecture-design.md`) + rev3 델타(`2026-06-10-architecture-rev3-delta.md`).
> 이 문서는 "배포까지의 전체 계획"을 확정한다. 충돌 시 이 문서 > rev3 델타 > rev2.

## 확정된 결정 (사용자, 2026-06-10)

| 항목 | 결정 |
|---|---|
| 목표 | 교내 실사용 서비스 (시연 아님) |
| 데드라인 | 없음 — 품질 우선 순차 진행 |
| 클라이언트 | Flutter 앱 + React 웹 둘 다 |
| 인프라 예산 | 월 1~5만원 |
| 유저 규모 | 학과 단위 ~수백명, 가입 = 학교메일(@smail.kongju.ac.kr) 인증 |
| 1차 오픈 범위 | RAG 챗봇 + 공지 + 포털 연동 전부 (시간표·성적·LMS·상담신청 툴콜) |
| 인프라 방식 | **A안: 단일 VPS + docker compose** (B 매니지드: 예산 초과 / C 무료티어: pgvector 용량·상시 워커 불가로 탈락) |
| Playwright | **Webcrea 포털 인증·툴콜에만 잔류 (제거 불가). 그 외 전부 제거** — 서버 가용성 확보 목적 |

## 1. 배포 토폴로지

```
VPS 1대 (4GB 시작, 부족 시 8GB 업글 — compose라 이전 ~5분) + 도메인 1개
└─ docker compose
   ├─ caddy      # TLS 자동발급, React SPA 정적 서빙, /api 리버스프록시, SSE 버퍼링 off
   ├─ api        # slim 이미지: FastAPI+uvicorn (Playwright/LibreOffice/torch 제외)
   ├─ worker     # heavy 이미지: Arq + Playwright(chromium) + LibreOffice + poppler + JRE
   ├─ redis      # Arq 잡큐 + 레이트리밋 카운터 + 암호화 세션쿠키(TTL)
   └─ postgres   # pgvector, named volume + 일일 pg_dump
```

- chromium은 이미지에 있되 **상시 구동 아님** — 포털 로그인 잡 때만 스파이크. 동시 실행 세마포어 1~2개로 RAM 피크 제한.
- prod LLM/임베딩 = OpenAI, 리랭커 = jina|local. **env 토글 유지** (파트너 로컬모델 경로 보존).
- 예상 월 비용: VPS 1.5~2.5만 + OpenAI 1~2만 ≈ **3~4.5만**.

## 2. 동기화 아키텍처 — "브라우저는 로그인 순간에만, 데이터는 전부 HTTP"

| 작업 | 방식 | Playwright |
|---|---|---|
| 메인 공지 | **Arq cron 폴링 (10~30분)**: 목록 페이지 httpx+bs4 → DB url unique와 diff → 신규만 크롤 잡 enqueue → 첨부파싱·임베딩·upsert | ❌ 제거 (정적 HTML — fix/86에서 검증) |
| 포털정보 (시간표·성적) | 유저 **동기화 버튼** → 온디맨드 잡 | 로그인만 |
| LMS | 로그인 1회(Playwright) → **세션쿠키 추출 → 이후 arrData/JSON은 httpx 고빈도 폴링**. 세션 만료까지 백그라운드 갱신 | 로그인만 |
| 상담신청 툴콜 | 온디맨드 단발 잡 (`fn_runFileMDI`) | 필수 잔류 |

- 야간 배치 폐기 → 폴링 cron. 공지 반영 지연 24h → 10~30분. 스케줄러는 Arq cron 1개 (rev2 C7 유지).
- 세션쿠키: Redis에 암호화+TTL 보관. **서버는 비번 영속 저장 없음** (rev2 위협모델 유지).
- 크롤 0행/연속 실패 → Slack webhook (셀렉터 깨짐 감지).

## 3. UX 요구사항 (검토에서 나온 8건 — 구현 단계에 내장, 후부착 불가 항목 명시)

### 🔴 설계 내장 필수
1. **포털 비번 = 앱 secure storage(디바이스) 저장.** 세션 만료 시 앱이 자동 재제출 → 매번 입력 제거. 서버 위협모델 불변. UI: "마지막 동기화 N분 전" + 만료 시 "재연결 필요" 배지.
2. **동기화 = 202 즉시 반환 + 진행 단계 표시** (로그인 중 → 가져오는 중 → 완료). 진행 중 잡 존재 시 기존 job_id 반환(중복 enqueue 차단). 완료 시 화면 자동 갱신.
3. **상담신청 툴콜 2단계**: LLM이 신청 내용 미리보기 생성 → 유저 확인 버튼 → 실행 → 영수증 표시. *툴콜 설계에 처음부터 내장 — 후부착 불가.*

### 🟡 계획 반영
4. **웹 SPA = iOS 커버 담당** (APK는 안드로이드만, iOS 직배포 불가). 웹을 앱 배포보다 먼저, 기능 동등성 유지.
5. **`/api/health`에 `min_app_version` 포함** → 앱 시작 시 체크, 미달 시 강제 업데이트 안내. *APK 직배포는 자동 업데이트 없음 — 첫 배포판부터 포함 필수, 후부착 불가.*
6. **온보딩 1줄 통합**: 가입(메일인증) → 선택 단계 "포털 연결" 유도 + "포털 비밀번호는 서버에 저장되지 않습니다" 문구. 계정 2개 혼란 해소.

### 🟢 구현 시 주의
7. 메일 인증: 재발송 쿨다운 60초 + "스팸함 확인" 안내 + 코드 TTL 10분.
8. 에러 문구: 429 → "잠시 후 다시 시도해주세요" 등 유저용 한국어 detail. 401(JWT 만료) → 로그인 화면 이동 + "세션 만료" 토스트. dart `_handleError`가 detail을 그대로 노출하므로 detail 자체를 유저용으로 작성.

## 4. 비용·보안 방어

1. 가입 = 학교메일 인증 (Resend/Gmail SMTP 무료 티어) → 외부인 차단 = LLM 비용 1차 방어.
2. 레이트리밋 (slowapi+redis): auth = IP 기반, chat = 유저당 분당+일당 상한.
3. OpenAI 대시보드 월 hard limit + 알림.
4. JWT TTL 30일 유지 (학내 규모 허용). refresh 회전은 후순위 백로그.
5. 로그 스크럽: 비번·세션쿠키·job_id (rev2 §7 유지).

## 5. 운영·배포 파이프라인

- **CI/CD**: GitHub Actions — main 머지 → 이미지 빌드 → GHCR push → ssh `docker compose pull && up -d`.
- **백업**: pg_dump 일1회 cron(named volume 외부로) + 주1회 오프사이트 복사.
- **관측**: LangSmith(RAG 트레이스) + Sentry free(api/worker DSN 분리) + UptimeRobot(외부 헬스체크). 전부 무료 티어.
- **VPS 보안**: ufw 80/443/ssh만, ssh 키 전용, fail2ban.

## 6. 클라이언트 배포

- 웹: 같은 VPS caddy 정적 서빙. `openapi-typescript`로 `/openapi.json` → TS 타입 자동생성.
- 앱: APK 직배포(학과 단톡/QR) → 안정화 후 Play Store (개발자계정 $25, 심사 1~7일). dart 계약은 고정 입력 원칙 유지.

## 7. Phase 로드맵

```
P0 정리       PR #93/94/95 머지 → feat/89-fastapi-core → dev
P1 서버 완성   Flutter 로그인 연동 → 학교메일 인증 가입(UX 7) → 레이트리밋(UX 8)
              → migrations 러너 → SSE /api/chat/stream → notices 키셋
              → /api/health min_app_version (UX 5)
P2 동기화     공지 폴링 파이프라인(PW 제거) → Arq 워커+포털 온디맨드(UX 1·2)
              → LMS 세션쿠키 고빈도 → 상담신청 툴콜 2단계(UX 3)
P3 웹 SPA     React+Vite, iOS 커버(UX 4) — P2와 파트너 분업 병렬 가능
P4 배포       compose.prod + Dockerfile slim/heavy → VPS 셋업(4GB) → CI/CD → 백업 → 관측
P5 클라이언트  웹 서빙 → APK 직배포(UX 5 포함 필수) → Play Store
P6 안정화     폴링 간격 튜닝 → 비용 모니터링 → 장애 알림(Slack)
```

- P1 내부 순서 근거: 인증은 이미 머지됨 → 클라이언트 연동·비용 방어 먼저, migrations는 다음 스키마 변경(P2) 전 확보 (rev2 D13 원칙).
- 1 증분 = 1 브랜치 = 1 행동, 각 증분은 CLAUDE.md 5.2 work-start로 이슈 생성 후 착수.

## 8. Verification (오픈 게이트 — 전부 통과해야 공개)

- [ ] 외부인 가입 불가 (타 도메인 메일 거부) 확인
- [ ] chat 레이트리밋 발동 + 유저용 한국어 detail 확인
- [ ] 동기화 버튼: 진행 표시 → 완료 갱신, 연타 시 중복 잡 0건
- [ ] 상담신청: 미리보기→확인→실행 전 과정 + 확인 없이 실행되는 경로 없음
- [ ] 구버전 앱 시뮬레이션: min_app_version 미달 시 업데이트 안내 노출
- [ ] pg_dump 백업 파일에서 실제 복원 1회 성공
- [ ] UptimeRobot 다운 알림 수신 테스트
- [ ] iPhone에서 웹 SPA로 핵심 플로우(가입→챗→동기화) 완주
