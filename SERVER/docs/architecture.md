# KNU 서버 인터페이스 구조

KNU는 백엔드 프로세스를 클라이언트별로 복제하지 않습니다. 하나의 FastAPI
애플리케이션이 공통 도메인과 저장소를 사용하고, 바깥쪽 인터페이스만 소비자별로
분리합니다.

```text
React WEB ─────┐
               ├─ interfaces/http/shared ─┐
               └─ interfaces/http/web ────┤
                                           ├─ db / retrieval / sync / pipelines
Codmes Surface ── interfaces/http/codmes ──┤
Codmes AI ─────── interfaces/mcp ──────────┘
```

## 디렉터리 소유권

```text
SERVER/
├── api/
│   ├── main.py          # FastAPI 조립, middleware, lifespan만 담당
│   └── ...              # HTTP 공통 인증·보안·큐 보조 모듈
├── interfaces/
│   ├── http/
│   │   ├── shared/      # React와 Codmes가 함께 쓰는 인증·공지·내 정보
│   │   ├── web/         # React 전용 챗봇·검색·동기화 제어 API
│   │   ├── codmes/      # Codmes Surface 전용 data-only adapter
│   │   ├── schemas/     # HTTP 요청·응답 DTO
│   │   └── routes.py    # 세 그룹을 기존 /api 경로에 등록
│   └── mcp/
│       └── server.py    # AI가 호출하는 공지 검색·상세 조회 도구
├── db/                  # PostgreSQL/pgvector 저장소
├── retrieval/           # 검색·리랭킹·RAG
├── sync/                # 포털·LMS 동기화
├── pipelines/           # 공지 수집·정제·임베딩
└── workers/             # Redis/ARQ 백그라운드 작업
```

## 인터페이스별 API

| 경계 | 대표 API | 소비자 |
|---|---|---|
| `http/shared` | `/api/auth/*`, `/api/notices`, `/api/me/*` | React, Codmes |
| `http/web` | `/api/chat`, `/api/search`, `/api/portal/sync/*`, `/api/lms/sync/*` | React |
| `http/codmes` | `/api/codmes/data/portal` | Codmes Surface |
| `mcp` | `/api/mcp` | Codmes AI |

공유 API는 중복 구현하지 않습니다. 예를 들어 공지와 로그인 상태는 React와
Codmes가 동일한 API를 사용하므로 `shared`에 둡니다.

## 변경 규칙

1. React 화면만 필요한 엔드포인트는 `interfaces/http/web`에 추가합니다.
2. Codmes 선언형 Surface 전용 변환은 `interfaces/http/codmes`에 추가합니다.
3. 양쪽이 동일한 데이터 계약을 쓰면 `interfaces/http/shared`에 추가합니다.
4. AI 도구는 HTTP 라우터에 섞지 않고 `interfaces/mcp`에 추가합니다.
5. DB·검색·동기화 로직은 인터페이스에서 직접 복제하지 않고 기존 공통 모듈을 호출합니다.
6. 외부 URL을 변경하지 않고 `interfaces/http/routes.py`에서 조립합니다.

이 구조는 코드 소유권만 분리합니다. 운영 서버는 여전히 하나이며 React 정적
파일 서버(Caddy/Vite)만 별도 프로세스로 실행됩니다.
