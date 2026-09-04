# KNU AI Assistant

공주대학교 공지와 학과 자료를 크롤링해 PostgreSQL/pgvector에 저장하고, FastAPI와 LangGraph 기반 RAG 챗봇으로 제공하는 학생 맞춤형 안내 서비스입니다.

독립 웹 제품은 `apps/web/`의 React/Vite 클라이언트이고, Codmes 플러그인은 네이티브 Surface와 MCP를 사용합니다. `services/api/`는 두 클라이언트가 공유하는 FastAPI 백엔드와 Redis/ARQ 백그라운드 작업을 제공합니다. 자세한 경계는 [architecture.md](architecture.md)를 참고합니다.

## 현재 기능

- 공주대학교 학생 공지 크롤링
- 컴퓨터공학과 학과공지 크롤링
- 경영학과 학과공지 크롤링
- 컴퓨터공학과 교과과정표 PDF 결정론적 파싱
- 경영학과 교과과정표 HWP 텍스트 추출
- 본문 이미지 OCR, 이미지/PDF/HWPX/HWP/XLSX/XLS/ZIP 첨부 텍스트 추출
- LLM 기반 `summary`, `category`, `target`, `start_date`, `end_date`, `keywords` 생성
- 원문 `content` 보존 및 청크 임베딩 저장
- 카테고리별 물리 테이블과 pgvector HNSW 검색
- chunk-first retrieval + BGE reranker 기반 evidence-centric RAG
- router → retriever → reranker → answerer 기반 LangGraph RAG 파이프라인
- optional verifier 기반 답변 충실도 검증
- 사용자 학과/관심사 기반 홈 추천과 공지 목록
- LMS(Canvas API) 할 일/강의/공지 동기화
- KNUIS 포털 졸업학점/성적/시간표 동기화

## 구조

```text
.
├── api/                           # FastAPI 조립·lifespan·공통 HTTP 보조 모듈
├── interfaces/
│   ├── http/
│   │   ├── shared/                # React/Codmes 공용 인증·공지·내 정보
│   │   ├── web/                   # React 전용 챗봇·검색·동기화 API
│   │   ├── codmes/                # Codmes Surface 전용 data adapter
│   │   ├── schemas/               # HTTP 요청·응답 DTO
│   │   └── routes.py              # 기존 /api URL 조립
│   └── mcp/                       # Codmes AI용 MCP 도구
├── workers/
│   └── arq_worker.py              # Redis/ARQ 워커와 공지 폴링
│
├── db/                            # 데이터베이스 패키지 모듈
│   ├── __init__.py                # DB façade (공개 API 재export)
│   ├── schema.py                  # DB URL/slug/스키마 init
│   ├── documents.py               # 문서/청크/검색 로직
│   ├── users.py                   # 프로필 저장/조회
│   └── lms.py                     # LMS 테이블 저장/조회
│
├── config.py                      # 전역 runtime/config 관리 (루트로 복원)
├── model.py                       # LLM/Embedding/Reranker 설정 (루트로 복원)
├── schema.py                      # 구조화 출력 스키마 (루트로 복원)
├── sitecustomize.py               # pycache 라우팅 (루트로 복원)
├── integrations.py                # LMS·포털 연동 오케스트레이션 (루트로 복원)
│
├── pipelines/                     # 데이터 처리 파이프라인
│   ├── ingest.py                  # 크롤링/적재 배치 (main.py → 이름 변경)
│   ├── refine.py                  # LLM 메타데이터/요약 정제 (Gemini batch)
│   └── rag_flow.md                # RAG 흐름 설명
│
├── sync/                          # 외부 시스템 동기화
│   ├── knuis_sync.py              # KNUIS 포털 동기화 (Playwright + arrData)
│   ├── lms_sync.py                # Canvas LMS 동기화 (API + LearningX)
│   └── lms_login.py               # LMS 로그인 세션 저장
│
├── crawlers/                      # 크롤러
│   ├── registry.py                # 크롤러 등록
│   ├── methods/                   # 공통 크롤러 구현
│   │   ├── board_notice.py        # 게시판 공지 크롤링
│   │   ├── curriculum_page.py     # 교과과정 페이지 크롤링
│   │   └── static_page.py         # 정적 페이지 크롤링
│   └── sites/                     # 사이트/학과별 크롤러 설정
│       ├── kongju.py              # 공주대학교 공통
│       └── departments/           # 학과별
│           ├── computer.py        # 컴퓨터공학과
│           └── business.py        # 경영학과
│
├── extractors/
│   └── attachments.py             # 첨부파일/본문 이미지 텍스트 추출
├── parsers/
│   ├── curriculum.py              # 교과과정표 parser (HWP 계열)
│   └── pdf_parser.py              # 교과과정표 PDF 결정론적 파싱
├── embedding/
│   └── embed.py                   # 청킹 및 임베딩
├── retrieval/
│   ├── graph.py                   # LangGraph RAG
│   └── rerank.py                  # BGE reranker 래퍼
│   ├── prompts.py                 # router/answerer/verifier 프롬프트
│   └── context_packing.py         # 컨텍스트 패킹/카드 렌더 헬퍼
├── debugtools/
│   └── crawl_one.py               # 단일 URL 테스트 리포트
├── docs/                          # 문서
│   ├── api.md                     # (현재 파일)
│   └── crawling_guide.md          # 크롤링 가이드
├── data/                          # 생성 데이터 (gitignore 처리)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 실행 시작점과 실제 흐름

로컬 개발은 DB·Redis를 Compose로 실행한 뒤 FastAPI, ARQ 워커, apps/web/Vite를 각각 시작합니다.

```text
apps/web/Vite
  → /api 프록시
  → api/main.py (FastAPI)
     → db/retrieval
     → Redis → workers/arq_worker.py (ARQ: LMS·포털 동기화, 공지 폴링)
```

FastAPI는 `Dockerfile.api`를 사용하고, 무거운 `Dockerfile`은 ARQ 워커를 기본 실행합니다. `pipelines/ingest.py`는 별도 배치 실행용이며, 답변 생성과 검색은 `retrieval/graph.py`가 담당합니다.

### 1. 크롤링 → 저장 (pipelines/ingest.py)

```text
크롤러 수집
→ extractors/attachments.py가 본문 이미지 OCR + 첨부파일 텍스트 추출
→ pipelines/refine.py에서 LLM(Gemini batch)으로 summary/category/target/date/keywords 생성
→ db/documents.py (또는 db): document_* 테이블에 원문 content + summary 저장
→ db/documents.py (또는 db): document_asset 테이블에 첨부파일 메타데이터 저장
→ embedding/embed.py에서 body + attachment chunk 청킹 및 임베딩
→ db/documents.py (또는 db): document_*_chunk 테이블에 vector 저장 (HNSW 인덱스)
```

### 2. RAG 검색/답변 (retrieval/graph.py)

```text
사용자 질문
→ [router_node] 질문 분석 (precise/broad 분류 + 카테고리 선정 + 쿼리 확장)
→ [retriever_node] vector similarity 검색 → BGE reranker 재정렬
→ [answerer_node] evidence chunk + support document context packing → LLM 답변 생성
→ [verifier_node] (optional) 답변 충실도 검증
```

### 3. LMS/KNUIS 동기화 (sync/)

```text
Canvas API (lms_sync.py):
  → 과목 목록 / planner items / announcements / todo items
  → LearningX API 미시청 동영상 강의
  → users 테이블 + lms_tasks / lms_courses 저장

KNUIS 포털 동기화 (sync/knuis_sync.py):
  → Playwright headless 로그인
  → Webcrea arrData 직접 파싱 (졸업학점/성적분포/누적성적/시간표)
  → users 테이블에 JSONB 저장
```

## 데이터베이스

PostgreSQL 16 + pgvector를 사용합니다.

### 문서 테이블 (카테고리별 분리)

```text
document_scholarship  (장학)
document_academic     (수강)
document_career       (취업/진로)
document_event        (행사/공모전)
document_etc          (일반/기타)

-- 각 문서는 source(게시판 출처) 테이블을 참조
```

각 문서 테이블의 핵심 컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `source_id` | `source.id` 참조 (게시판 출처) |
| `url` | 원문 URL, unique |
| `title` | 제목 |
| `content` | 원문 본문 + OCR + 첨부 추출 텍스트 (풀 텍스트) |
| `body_content` | 본문 원본 (별도 보존) |
| `attachment_names` | 첨부파일명 리스트 (JSONB) |
| `attachment_contents` | 첨부파일 추출 텍스트 (JSONB) |
| `summary` | LLM 요약 (2~3문장) |
| `posted_at` | 게시글 등록일 |
| `start_date`, `end_date` | 접수/행사 기간 |
| `is_pinned` | 게시판 고정 공지 보존 플래그 |
| `target` | 학년/재적상태 대상 (배열) |
| `keywords` | 추천/필터용 키워드 (배열) |
| `extra` | 교과과정표 등 구조화 부가 데이터 (JSONB) |

### 청크 테이블 (카테고리별 분리)

```text
document_scholarship_chunk
document_academic_chunk
document_career_chunk
document_event_chunk
document_etc_chunk

각 청크: (document_id, chunk_idx, content, chunk_type, attachment_name, embedding vector)
- chunk_type: 'body' 또는 'attachment'
- attachment_name: 청크가 속한 첨부파일명 (attachment 청크만)
- embedding: EMBEDDING_DIM 차원 vector (HNSW cosine index)
```

### 사용자/동기화 테이블

```text
users               (student_id, name, major, year, interests, favorite_courses,
                     graduation_credits JSONB, timetable JSONB,
                     grade_distribution_json JSONB, cumulative_grades_json JSONB)
lms_tasks           (student_id, task_type, title, course_name, due_date, ...)
lms_courses         (student_id, course_id, course_name)
document_asset      (category, document_id, kind, filename, source_url, ...)
```

## 청킹 및 임베딩 (embedding/embed.py)

### 청킹 전략

- **CHUNK_SIZE = 280자**, **CHUNK_OVERLAP = 80자** (`embedding/embed.py` 모듈 상수)
- `chunk_text()`가 `RecursiveCharacterTextSplitter` 없이 줄 경계 + 표 문맥을 고려해 자체적으로 분할한다.
  - XLSX 표가 잘릴 경우 `_table_context_prefix()`가 현재 시트/헤더를 청크 앞에 보강한다.
- attachment_contents는 item별로 별도 청킹 (chunk_type='attachment')
- attachment_name을 청크 메타데이터로 보존
- 본문 이미지 OCR 텍스트는 body_content에 통합된 후 함께 청킹

### 임베딩

- Provider: LM Studio(local), OpenAI, Google 중 선택
- EMBEDDING_DIM: 환경변수로 설정 (모델에 맞게 지정)
- 모든 청크는 EMBEDDING_DIM 차원의 float32 vector로 임베딩
- 저장 후 pgvector HNSW cosine 인덱스 자동 생성

## LLM 메타데이터 정제 (pipelines/refine.py)

### refine 입력

- body_content 우선 사용 (원문 보존)
- body가 충분하면(>= 1000자): attachment는 파일명만 LLM에 전달
- body가 빈약하면: attachment excerpt(최대 10000자) 포함

### 처리 방식

- Gemini API `with_structured_output(MetadataSchema)` 사용
- `model.batch()`로 최대 10개 동시 처리
- 실패 항목은 지수 백오프 재시도 (최대 4회)
- 모든 실패 항목은 해당 문서만 드롭 (전체 배치 중단 없음)

### 추출 항목 (MetadataSchema)

| 필드 | 설명 |
|------|------|
| `category` | 5개 고정 대분류 중 1개 |
| `summary` | 2~3문장 핵심 요약 |
| `target` | 학년/재적상태 제한 (없으면 ["전체"]) |
| `start_date` | 접수 시작일 (yyyy-mm-dd) |
| `end_date` | 접수 마감일 (yyyy-mm-dd) |
| `keywords` | 핵심 해시태그 1~3개 |
| `title` | 원문 제목 (덮어쓰기) |
| `content` | 원문 본문 (LLM 축소 방지용 덮어쓰기) |

날짜 보정: LLM이 연도 없는 날짜에 추정 연도를 붙인 경우, 게시글 등록연도로 자동 보정.

## RAG 검색/답변 (retrieval/graph.py)

### LangGraph 파이프라인 구조

```
                    ┌──────────┐
                    │  router  │
                    └────┬─────┘
                         │
                  ┌──────┴──────┐
                  │ query_mode  │
                  └──────┬──────┘
                         │
            ┌────────────┴────────────┐
            │ precise                 │ broad
            ▼                         ▼
    ┌───────────────┐       ┌──────────────────┐
    │   retriever   │       │ broad_retriever   │
    │ (vector+rerank)│       │ (DISTINCT ON doc) │
    └───────┬───────┘       └────────┬─────────┘
            │                        │
            ▼                        ▼
    ┌───────────────┐       ┌──────────────────┐
    │   answerer    │       │ broad_answerer    │
    │ (evidence+doc)│       │ (메타카드 목록)   │
    └───────┬───────┘       └────────┬─────────┘
            │                        │
            ▼                        ▼
    ┌───────────────┐              END
    │  verifier     │ (ENABLE_VERIFIER=true 시)
    │  (충실도 검증)│
    └───────┬───────┘
            ▼
          END
```

### 1. 라우터 노드 (router_node)

질문을 LLM에 전달해 다음 3가지를 결정:

| 결정 필드 | 설명 |
|-----------|------|
| `query_mode` | `precise`(특정 공지 1건) 또는 `broad`(여러 공지 목록) |
| `categories` | 검색 대상 카테고리 리스트 (0~5개) |
| `expanded_query` | 격식체/도메인 유의어를 반영한 검색용 확장 쿼리 |

라우터 시스템 프롬프트 핵심 규칙:
- 애매하면 `precise` 선택 (안전 기본값)
- "알려줘/조회해/보여줘" 같은 서술어 제거
- 핵심 명사 + 도메인 유의어 2~4개 추가 (과확장 금지)

### 2. retriever 노드 (precise 경로)

`_retrieve_with_rerank()` 함수 실행:

```
1. embed_query(expanded_query) → query vector
2. db.search_chunks(): 5개 카테고리 UNION ALL vector similarity 검색
   → LIMIT RERANK_CANDIDATES(default 50)
3. BGE reranker로 chunk 단위 재정렬
4. 상위 EVIDENCE_TOP_K(=RERANK_TOP_N, default 5) = evidence chunks
5. 문서 단위 best score 집계 → top SUPPORT_DOC_TOP_N(default 3) 선정
6. evidence chunk 텍스트는 support document body에서 dedup 제거
7. evidence chunks + support documents 반환
```

검색 시 학과 필터: 사용자 프로필의 `major`와 `source.department` 매칭 (department='공통' 또는 NULL도 포함)

### 3. broad_retriever 노드 (broad 경로)

- `DISTINCT ON (d.url)`로 공지당 1 chunk만 후보로 참여
- `search_chunks(limit=BROAD_RERANK_CANDIDATES=50, distinct_by_doc=True)`
- rerank 후 상위 BROAD_DOC_TOP_N(default 12)개 반환
- evidence chunk packing / full-doc fetch 없음 (가벼운 목록)

### 4. answerer 노드 (precise)

#### context packing 전략 (_pack_contexts)

evidence chunk(35% budget) + support document context(65% budget)를 단일 prompt로 패킹:

**evidence chunk 포맷:**
```
# 핵심 검색 청크

[1] 제목
URL: ...
청크본문

[2] 제목
...
```

**1등 support document (_format_context_with_budget):**
```
[제목](URL)
접수기간: yyyy-mm-dd ~ yyyy-mm-dd

[본문]
body full 우선 보존 (80% budget)
첨부파일명은 메타데이터만 (본문 미포함)
```

**2~3등 support document (_format_support_context):**
```
[제목](URL)

[요약]
summary 우선

[검색 매칭 청크]
rerank matched chunk

[본문 일부]
body 일부 (50% budget)
```

#### 답변 생성

- System prompt: "반드시 컨텍스트만 근거로 답변"
- Human message: 오늘 날짜 + 사용자 질문 + 패킹된 컨텍스트
- 답변 끝에 참고 공지 제목/URL 목록 첨부
- 내부 분석/추론 과정 출력 금지

### 5. broad_answerer 노드 (broad)

- 공지를 메타카드(제목+URL+접수기간+요약) 목록으로 렌더
- budget(6000자) 안에서 가능한 한 많은 카드 포함

### 6. verifier 노드 (optional)

`ENABLE_VERIFIER=true`일 때만 precise 경로 끝에 연결:

| 판정 | 조건 |
|------|------|
| `grounded=True` | 답변의 모든 사실이 컨텍스트에 명시됨 |
| `grounded=True` | 컨텍스트 사실 + 오늘 날짜에서 논리적 도출 가능 |
| `grounded=True` | 컨텍스트가 비었거나 무관 → 정직한 회피 |
| `grounded=False` | 컨텍스트에 없는 내용 단정 (할루시네이션) |
| `grounded=False` | 컨텍스트에 정보가 명백히 있는데 회피 |

`fidelity`: 0.0(전부 환각) ~ 1.0(전부 근거 있음)

### 검색/답변 설정

```env
RERANK_CANDIDATES=50                  # vector 검색 후보 수 (config.py 기본값)
RERANK_TOP_N=5                        # evidence chunk 수 (config.py 기본값)
SUPPORT_DOC_TOP_N=3                   # support document 수
BROAD_RERANK_CANDIDATES=50            # broad 경로 후보 수
BROAD_DOC_TOP_N=12                    # broad 경로 문서 수
ANSWER_CONTEXT_BUDGET_RATIO=0.70      # answerer context budget 비율 (CONTEXT_WINDOW_CHARS에 곱함)
VERIFIER_CONTEXT_BUDGET_RATIO=0.20    # verifier context budget 비율
ATTACHMENT_NAME_RESERVE_RATIO=0.13    # support doc 본문 예산 중 첨부파일명 표기에 예약할 비율
ENABLE_VERIFIER=false                 # verifier 활성화
```

- answerer/verifier의 context budget은 정해진 char 수치가 아니라 `CONTEXT_WINDOW_CHARS(=max(4000, LLM_MAX_CONTEXT_WINDOW_TOKENS * LLM_CHARS_PER_TOKEN))` × 각 비율로 계산한다.
- `LLM_MAX_CONTEXT_WINDOW_TOKENS`(기본 60000) × `LLM_CHARS_PER_TOKEN`(기본 1.5)로 컨텍스트 윈도우 글자 수가 동적으로 결정된다.
- `CHUNK_SIZE`/`CHUNK_OVERLAP`은 환경변수가 아니라 `embedding/embed.py`의 모듈 상수(280/80)다.

## 리랭커 (retrieval/rerank.py)

### 제공자 선택

`config.RERANKER_PROVIDER`로 결정:

| 값 | 방식 | 특징 |
|-----|------|------|
| `local` (기본) | BAAI/bge-reranker-v2-m3 CrossEncoder | 로컬, 무료, `sentence-transformers` |
| `jina` | Jina Reranker v3 API | API 키 필요, JINA_API_KEY 환경변수 |

### rerank_scores(query, passages) → List[float]

- local: CrossEncoder.predict() → sigmoid 변환 (0~1)
- jina: urllib POST → relevance_score 매핑 (0~1)
- 둘 다 입력 순서 그대로 점수 리스트 반환 (재정렬은 graph.py에서 수행)

## LMS 동기화 (sync/lms_sync.py)

### Canvas API 연동

| API | 용도 | 동기화 항목 |
|-----|------|-----------|
| `/api/v1/courses` | 수강 과목 목록 | lms_courses 저장 |
| `/api/v1/users/self/favorites/courses` | 즐겨찾기 과목 | users.favorite_courses 갱신 |
| `/api/v1/planner/items` | planner 할 일 | 과제/공지 upsert (source='canvas') |
| `/api/v1/users/self/todo` | todo 항목 | 과제 upsert |
| `/api/v1/announcements` | 강좌별 공지 | lms_tasks upsert (notice type) |
| `/api/v1/courses/{id}/modules` | 강의 모듈 | 미시청 attendance_item upsert (lecture type) |

### LearningX 동기화

- Canvas Access Token으로 LearningX 세션 쿠키(xn_api_token) 백그라운드 갱신
- `_get_learningx_modules()`: LearningX API로 미시청 동영상 강의 조회
- content_type='attendance_item' + 미완료 항목만 저장
- content_data의 content_type이 mp4/movie/readystream인 경우만 저장

### 세션 관리

- Playwright storage_state에 쿠키 저장 (.secrets/lms_storage_state.json)
- Canvas Access Token 자동 발급 (lms_login.py에서 profile/settings 페이지 진입)
- 토큰 파일 (.secrets/lms_canvas_token.txt)

## KNUIS 포털 동기화 (sync/knuis_sync.py)

### 로그인

- Playwright headless chromium으로 portal.kongju.ac.kr 로그인
- 통합정보시스템 버튼 클릭 → 새 탭 진입
- LeftFrame의 `fn_runFileMDI()` 직접 호출로 메뉴 진입 (DOM 트리 탐색 우회)

### 데이터 파싱 방식

**Webcrea arrData 직접 읽기** (DOM 파싱 대신):
DOM 대신 JavaScript `Webcrea.GetObjectById(gid).arrData`에서 컬럼지향 데이터 직접 추출. 가상화로 인한 행 누락 없이 전체 행 획득 가능.

### 수집 데이터

| 메뉴 | menuId | 테이블 | 저장 필드 |
|------|--------|--------|----------|
| 시간표 | 1000000062 | G1 arrData | `users.timetable` JSONB |
| 나의 성적분포 | 1000000103 | G1 + F1 arrData | `users.grade_distribution_json` JSONB |
| 누적성적조회 | 1000000102 | G1/G2/G3 arrData | `users.cumulative_grades_json` JSONB |
| 졸업사전예고 | 1000000111 | F_SRCH + G4 arrData | 학적(name, major, year) + `users.graduation_credits` JSONB |

### 동기화 실행 (통합)

```
포털 로그인
→ [3/8] 시간표 파싱
→ [4/8] 나의 성적분포 파싱
→ [5/8] 누적성적조회 파싱 (전체 학기 강제 선택)
→ [6/8] 졸업사전예고 파싱
→ [7/8] DB 일괄 저장 (upsert_user)
```

## 문서 정리 정책

`pipelines/ingest.py`는 더 이상 DB를 전체 초기화하지 않습니다.

실행 시:
1. `init_db()`로 스키마를 비파괴 준비
2. 현재 게시판의 고정 공지 URL 수집
3. `is_pinned` 동기화
4. 24개월보다 오래됐거나 마감된 문서를 과거 공지로 보관
5. `crawl_url_state`에 정규화 URL별 `discovered/completed/failed` 상태 저장
6. 완료된 과거 URL은 상세 크롤링/OCR 생략
7. 신규·실패 URL과 최근 7일의 현재 추출 버전 URL을 상세 처리
8. 이전 추출 버전의 완료 URL은 `refresh_outdated_extraction=true`인 수동
   크롤링에서만 현재 버전으로 재처리

전체 크롤링은 현재 페이지가 모두 기존 URL이어도 종료하지 않고 실제
마지막 목록 페이지까지 계속한다. 부분 크롤링으로 3~20페이지를
먼저 처리했더라도, 뒤의 전체 크롤링은 21페이지 이후까지 URL을 계속
확인한다. 페이지 번호는 중복 판단에 사용하지 않는다.

고정 공지는 24개월이 지나도 보관된다.

Server Manager의 데이터 화면은 `GET /api/admin/notices`의 공지 소스,
카테고리, 시작일~종료일 날짜 범위, 현재/과거 상태, 추출 버전 조건을
조합해 저장 결과를 조회한다. `crawl_enabled=false`이면 예약 수집만
건너뛰며 수동 수집과 API 서버는 계속 동작한다.

`GET /api/admin/tools`는 FastMCP에 현재 등록된 도구의 이름, 그룹, 설명,
입력 JSON Schema, 활성 상태와 MCP 안전 annotation을 그대로 반환한다. Manager가
표시용 목록을 별도로 관리하지 않으므로 MCP 도구 추가·삭제가 이 응답에 자동 반영된다.

## 첨부파일 처리

| 형식 | 처리 |
| --- | --- |
| 본문 이미지 | HTML DOM 순서로 `[본문 그림 N]` 위치·앞뒤 문맥을 보존하고 VLM OCR·설명·독립 청크·`inline_image` asset 저장 |
| 이미지 첨부 | VLM OCR, 원본 이미지 sha1 파일 저장 |
| PDF | `pdfplumber` 텍스트 추출, 텍스트가 없으면 `pdf2image` + VLM OCR. 내장 그림은 페이지 단위 문맥과 함께 별도 저장 |
| DOCX | OOXML 문단 관계를 따라 텍스트와 내장 그림의 실제 문단 위치를 함께 추출 |
| HWPX | ZIP/XML 구조 파싱으로 문단·표를 추출하고 `binaryItemIDRef`로 그림 위치 연결 |
| HWP | `syhwp` 문단·표 구조 + 독립 BodyText 파서 + 패치된 HWP→HWPX 검사본을 교차 비교하고 BinData 원본 보존 |
| PPTX | `python-pptx`로 텍스트 프레임·표를 추출하고 슬라이드·도형 순서로 그림 연결 |
| PPT | 정확한 구조 파서가 없어 원본을 검토 대상으로 보존 |
| XLSX | `openpyxl`로 전체 추출, 표 헤더 보존. drawing anchor로 그림을 시트·셀에 연결 |
| XLS | `xlrd`로 전체 추출, 표 헤더 보존 |
| ZIP | 내부의 PDF/HWPX/HWP/XLSX/이미지를 풀어 각각 기존 파이프라인으로 처리 |
| 기타 | 안내문 저장 |

XLSX는 행마다 헤더를 반복하지 않고 `[표 헤더]`, `[행]` 형식으로 저장합니다. 청킹 중 표가 잘리면 `embedding/embed.py`가 현재 시트/헤더를 청크 앞에 보강합니다.

## 환경변수

`.env` 예시:

```bash
# Database
DB_PASSWORD=your_db_password
DB_USER=knu-uic
DB_NAME=knu-uic
DB_HOST=localhost
DB_PORT=5432
DATABASE_URL=postgresql://knu-uic:pass@localhost:5432/knu-uic

# LLM Provider (local / google / openai)
VLM_PROVIDER=local
LLM_MODEL=gemma-4-12b-it-mlx

# Embedding
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIM=768

# LM Studio
LOCAL_LLM_PORT=1234
LOCAL_LLM_TEMPERATURE=0
LOCAL_LLM_MAX_TOKENS=2048
LOCAL_LLM_TIMEOUT_SECONDS=180

# Retrieval
RERANK_CANDIDATES=50
RERANK_TOP_N=5
SUPPORT_DOC_TOP_N=3
BROAD_RERANK_CANDIDATES=50
BROAD_DOC_TOP_N=12

# Context
LLM_MAX_CONTEXT_WINDOW_TOKENS=32768
LLM_CHARS_PER_TOKEN=1.5
REFINE_FULL_CONTENT_LIMIT=24000
ATTACHMENT_REFINE_FALLBACK_CHARS=16000
ANSWER_CONTEXT_BUDGET_RATIO=0.70        # answerer context budget 비율
VERIFIER_CONTEXT_BUDGET_RATIO=0.20      # verifier context budget 비율
ATTACHMENT_NAME_RESERVE_RATIO=0.13      # support doc 본문 예산 중 첨부파일명 표기 예약 비율
# 참고: ANSWER_CONTEXT_CHAR_BUDGET 같은 고정 char 수치는 config.py에 없음.
#       context budget = CONTEXT_WINDOW_CHARS(=max(4000, LLM_MAX_CONTEXT_WINDOW_TOKENS * LLM_CHARS_PER_TOKEN)) * 비율

# Verifier
ENABLE_VERIFIER=false

# Refine
REFINE_FULL_CONTENT_LIMIT=24000
ATTACHMENT_REFINE_FALLBACK_CHARS=16000

# API Keys
GOOGLE_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
JINA_API_KEY=

# HWP/HWPX/PDF/DOCX/XLSX/PPTX 내부 그림
DOCUMENT_IMAGE_ANALYSIS_ENABLED=true
DOCUMENT_ASSETS_ROOT=data/assets

# Reranker
# 비워두면 JINA_API_KEY 유무에 따라 local(BGE CrossEncoder)/jina 자동 결정
RERANKER_PROVIDER=
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_MAX_LENGTH=512

# Crawling
MAX_CRAWL_WORKERS=4
CRAWL_HTTP_TIMEOUT_SECONDS=75
CRAWL_HTTP_MAX_ATTEMPTS=3
CRAWL_HTTP_BACKOFF_SECONDS=3
ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS=180000
ATTACHMENT_DOWNLOAD_RETRY_ATTEMPTS=3
ATTACHMENT_DOWNLOAD_BACKOFF_SECONDS=3
# CHUNK_SIZE/CHUNK_OVERLAP은 환경변수가 아니라 embedding/embed.py의 모듈 상수(280/80)다.

# LangSmith
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=knu-ai-assistant
```

provider 설정:
- `VLM_PROVIDER`: `local`, `google`, `openai` 중 선택
- `EMBEDDING_PROVIDER`: `local`, `google`, `openai` 중 선택
- `RERANKER_PROVIDER`: `local`(BGE CrossEncoder), `jina`(Jina API) 중 선택
- `DOCUMENT_IMAGE_ANALYSIS_ENABLED`: 지원 문서 형식의 내장 그림을 VLM으로 설명·OCR
- `DOCUMENT_ASSETS_ROOT`: 원본 문서, 구조 파일, 내장 그림을 보존할 루트

기존 배포의 `HWP_IMAGE_ANALYSIS_ENABLED`, `HWP_ASSETS_ROOT`는 호환용 fallback으로
계속 읽지만 새 설정 이름은 모든 문서 형식에 공통으로 적용된다.

Docker 환경에서 워커가 호스트의 LM Studio에 접근해야 하면 `http://host.docker.internal:1234/v1`을 사용합니다.

LM Studio에서 Gemma를 사용할 때는 실제 모델도 같은 컨텍스트 크기로 로드합니다.
환경변수는 앱의 입력 예산을 정할 뿐, 이미 로드된 모델의 컨텍스트를 바꾸지는 않습니다.

```bash
lms unload gemma-4-12b-it-mlx
lms load gemma-4-12b-it-mlx \
  --identifier gemma-4-12b-it-mlx \
  --context-length 32768 \
  --parallel 2 \
  --gpu max \
  --ttl 3600 \
  -y
lms ps
```

## 로컬 실행

DB·Redis만 Docker로 띄우고 FastAPI, ARQ 워커, apps/web/Vite는 로컬에서 실행하는 방식입니다.

```bash
docker compose up -d db redis

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium

# FastAPI HTTP API
python3 -m uvicorn api.main:app --port 8000

# 별도 터미널: Redis 잡 처리와 공지 폴링
arq workers.arq_worker.WorkerSettings

# 별도 터미널: apps/web/Vite
cd ../../apps/web && npm run dev

# LMS 동기화 (Canvas 계정 필요)
python3 -m sync.lms_login --auto           # 세션 저장
python3 -m sync.lms_sync                   # 할 일 동기화

# KNUIS 포털 동기화 (학번/비번 필요)
python3 -m sync.knuis_sync --username 학번 --password-stdin <<< "비밀번호"
```

스캔 PDF OCR을 쓰려면 로컬에도 poppler가 필요합니다. `opendataloader-pdf`와 선택적 HWP→HWPX 교차 검증에는 Java 11 이상이 필요합니다. Docker worker 이미지는 null BinData 확장자를 복구한 HWP→HWPX 검사기를 빌드해 포함합니다. LibreOffice는 사용하지 않습니다.

macOS:

```bash
brew install poppler
brew install openjdk@21
```

Homebrew의 `openjdk@21`이 시스템 기본 Java보다 뒤에 잡히는 환경에서는 서버를
실행할 때 `PATH="/opt/homebrew/bin:$PATH"`를 앞에 붙입니다.

로컬에서도 HWP→HWPX 2차 검증을 켜려면 한 번 빌드합니다. 생성된 JAR은 Git에
포함되지 않으며 코드가 자동으로 발견합니다.

```bash
./third_party/hwp2hwpx/build-local.sh
```

## Docker 실행

기본 Compose는 로컬 의존 서비스(DB·Redis)만 실행합니다.

```bash
docker compose up -d db redis
```

제품 컨테이너 구성은 별도의 프로덕션 Compose를 사용합니다. API는 `Dockerfile.api`, 워커는 `Dockerfile`, 웹은 `apps/web/`의 Caddy 이미지를 사용합니다.

```bash
docker compose -f docker-compose.prod.yml up --build
```

## 단일 URL 테스트

DB 저장 없이 특정 공지 하나만 크롤링하고 txt 리포트를 만들 수 있습니다.

```bash
python3 debugtools/crawl_one.py "https://www.kongju.ac.kr/bbs/KNU/2132/427500/artclView.do?layout=unknown"
```

결과는 기본적으로 `data/reports/`에 저장됩니다.

리포트에는 크롤링 결과, asset OCR/첨부 추출 결과, LLM refine 결과, embedding chunk가 포함됩니다. DB에는 저장하지 않습니다.

### 게시판 크롤링 안정성 정책

`BoardNoticeCrawler`는 상세 페이지 HTML을 retry 가능한 HTTP 요청으로 한 번만
가져와 제목·날짜·본문·첨부 링크·본문 이미지 주소를 파싱한다. 일반 공지와 일반
첨부 다운로드와 HWP 처리에는 Chromium을 사용하지 않는다. 구조 파서가 없는
일부 레거시 첨부 미리보기에만 Chromium을 lazy 실행하며, 한 크롤링 실행 안에서는
같은 browser/context를 재사용한다.

HWP는 미리보기나 PDF 렌더링을 사용하지 않는다. `syhwp` 구조 파서와 독립
BodyText 레코드 파서의 텍스트를 비교하고, Docker에서는 별도의 HWPX 변환본까지
비교한다. 기준 점수 0.94 미만 또는 변환 불일치는 `extraction_review`로 격리되어
검색·답변에 사용되지 않는다.

2024 국립공주대학교 요람 실물 테스트(24,569,856 bytes)에서 원본 구조 파서는
806,504자·표 1,488개·표 셀 42,956개·BinData 129개를 복원했다. 독립 BodyText
결과와 token F1은 0.99547였다. null 확장자 보정 후 생성한 22,344,521-byte HWPX
검사본은 원본 구조 텍스트와 token F1 0.981682였고, 표 1,490개와 BinData 129개를
보존했다. 최종 품질 점수는 0.993645로 자동 적재 기준을 통과했다.

HWP bundle은 하나의 Markdown만 저장하지 않는다. 원본 `.hwp`, 검색용
`document.md`, 표 셀·이미지 메타데이터·품질 수치가 포함된 canonical
`document.json`, 선택적 `validation.hwpx`, 원본 `images/*`를 함께 저장한다.

HWP 그림은 BinData 파일 정렬 순서를 사용하지 않고 문서의
`HWPTAG_SHAPE_COMPONENT_PICTURE` BinItem 참조를 읽어 실제 배치 순서로
`[그림 1]`, `[그림 2]` 처럼 번호를 붙인다. VLM에는 그림 바로 앞·뒤
문장과 표 행을 함께 제공한다. 검수를 통과한 설명과 OCR 텍스트는
`document.md`의 **원래 그림 위치 바로 뒤**에 삽입하고, 검색에서 다른
그림과 섞이지 않도록 그림별 독립 청크도 추가한다. 청킹 경계에서
설명과 번호가 나뉘어도 모든 설명 청크에 해당 `[그림 N]`을 복원한다.

같은 그림 계약을 공지 HTML 본문과 HWPX, DOCX, PPTX, XLSX, PDF에도 적용한다.
HTML 본문은 실제 `<img>` DOM 위치에 `[본문 그림 N]`을 넣고 앞뒤 문장과 `alt`
텍스트를 문맥으로 제공한다. 작은 아이콘·추적 이미지·로고는 제외하며, 본문
그림과 첨부 그림이 모두 `그림 1`이어도 서로 충돌하지 않는 별도 marker를 쓴다.
HWPX는 문단의
`binaryItemIDRef`, DOCX는 문단 relationship, PPTX는 슬라이드와 shape 순서,
XLSX는 drawing anchor 셀을 사용하므로 원문 위치와 문맥을 구조적으로 연결한다.
PDF는 객체가 속한 페이지까지는 확정할 수 있지만 일반 PDF의 그리기 명령만으로
문장 사이의 정확한 위치를 항상 복원할 수 없어 페이지 문맥 단위로 연결하며
신뢰도도 더 낮게 기록한다. 구형 DOC/XLS/PPT는 안정적인 내장 그림 위치 파서가
없으므로 현재 텍스트 추출과 원본 보존까지만 지원한다.

검색·채팅·MCP 근거에는 청크가 참조한 번호의 이미지만
`related_images`(asset ID, 안전한 참조 토큰, 번호, 설명, 문맥, 렌더링 URL)로 반환한다. 원본 이미지는
`GET /api/notice-assets/{asset_id}/content`에서 inline으로 제공되며, 문서 구조
JSON·Markdown·HWPX 검사본 자체는 임베딩하지 않는다. 악보는 원본 이미지와
확인된 제목·작사·작곡만 저장하며, OMR·사람 검토 없이 음표를 검색 사실로
채택하지 않는다.

`related_images`를 받은 Codmes 모델은 모든 그림을 답변 끝에 자동 첨부하지
않는다. 모델이 각 그림의 문맥과 설명을 보고 질문에 실제로 필요한 그림을
0개·1개·여러 개 선택하고, URL 대신 서버가 발급한 정확한 `[그림:assetId]`
토큰만 원하는 답변 위치에 쓴다. Codmes runtime은 **이번 도구 결과에 실제로
포함된 asset ID인지 다시 검증한 뒤에만** 해당 토큰을 안전한 Markdown 이미지로
치환한다. 따라서 모델은 이미지 바이트를 소유하거나 URL을 만들 필요가 없고,
허용되지 않은 ID를 추측해도 이미지로 렌더링되지 않는다. 토큰은 설명 앞·뒤나
연속된 위치 어디든 둘 수 있고, 선택하지 않은 그림은 자동 첨부되지 않는다.

공주대학교 공통 게시판 `main_notice`는 서버 실측 결과에 따라 `max_workers=2`를
사용한다. 전역 기본값은 `MAX_CRAWL_WORKERS=4`이며 다른 출처는 필요하면
`BoardNoticeConfig.max_workers`로 별도 제한할 수 있다.

2026-09-02 상세 HTTP 수집을 두 순서로 비교했다. 서버가 빠른 상태에서는 동시성
4가 더 높은 처리량을 보였지만, 느려진 상태에서는 동시성 4가 전건 실패한 반면
2는 전건 성공했다. 따라서 `2`는 항상 더 빠른 값이 아니라 장애 시 성공률을 위한
보수적인 운영값이다.

| 상태·표본 | 동시성 | 성공 | 실패 | 전체 시간 | 평균 요청 시간 |
|---|---:|---:|---:|---:|---:|
| 응답 지연, 최신 8건 | 2 | 8 | 0 | 1.87초 | 0.46초 |
| 응답 지연, 최신 8건 | 4 | 0 | 8 | 49.90초 | 24.40초 |
| 빠른 응답, 최신 4건(역순) | 4 | 4 | 0 | 0.28초 | 0.20초 |
| 빠른 응답, 최신 4건(역순) | 2 | 4 | 0 | 0.46초 | 0.19초 |

상세 HTML은 기본 75초 timeout과 최대 3회 재시도를 사용한다. 재시도 대기는
3초, 9초처럼 지수적으로 증가한다. 첨부 다운로드는 20MB 이상 파일을 고려해
기본 180초와 최대 3회 재시도를 사용한다.

각 목록 페이지는 이미 DB에 있는 URL과 이번 실행의 성공 건수를 합쳐 기본 50%,
최소 3건 이상 확인되어야 신규 결과를 적재 단계로 전달한다. 기준 미달 페이지의
부분 성공 결과는 보류하고 다음 실행에서 다시 수집한다. 이 판정은 24개월이 지난
공지의 시간 기반 보관 정책과 독립적이므로, 크롤링 실패 여부와 관계없이 오래된
공지는 과거 공지로 이동한다.

Manager와 worker는 다음 목록 범위를 지원한다.

- `all`: `._totPage`에서 실제 마지막 페이지를 읽어 전체 URL 대조
- `range`: 첫 N페이지 또는 시작~끝 페이지 범위
- `recent`: 고정 공지를 제외한 일반 공지가 최근 7일 기준을 벗어나는
  페이지까지 확인. 자동 수집은 이 모드를 사용

## 크롤러 추가

학과 게시판을 추가할 때는 `crawlers/sites/departments/`에 설정을 추가하고 `crawlers/registry.py`에 등록합니다.

학과 추천은 `source.department`와 사용자 프로필의 `major`를 비교합니다.
학교 공통 크롤러는 `source.department = '공통'`으로 저장합니다.

```sql
s.department = :major
OR s.department = '공통'
OR s.department IS NULL
```

따라서 학과 게시판 크롤러의 `department` 값을 정확히 넣는 것이 중요합니다.
`target`에는 학과명을 넣지 않고, 본문에 명시된 학년/재적상태 제한만 저장합니다.

## 검증 명령

```bash
python3 -m py_compile \
  api/main.py workers/arq_worker.py \
  pipelines/ingest.py pipelines/refine.py \
  config.py model.py schema.py integrations.py sitecustomize.py \
  db/__init__.py db/schema.py db/documents.py db/users.py db/lms.py \
  embedding/embed.py retrieval/graph.py retrieval/rerank.py \
  extractors/attachments.py parsers/curriculum.py \
  crawlers/registry.py crawlers/methods/*.py \
  crawlers/sites/*.py crawlers/sites/departments/*.py \
  debugtools/crawl_one.py \
  sync/knuis_sync.py sync/lms_sync.py sync/lms_login.py
```

requirements 파일 문법 확인:

```bash
python3 -m pip install --dry-run -r requirements.txt
```

## 주의사항

- 기존 DB에 이미 들어간 문서는 새 `summary` 컬럼이 비어 있을 수 있습니다. 재크롤링 또는 백필이 필요합니다.
- `.xls`도 `xlrd`로 텍스트화하지만, 서식/병합 셀 복원은 제한적입니다.
- `document_asset.extracted_text`는 디버깅/재처리용이고, 검색은 `document.content`에서 만들어진 chunk를 사용합니다.
- Docker에서 LM Studio를 쓰려면 호스트 LM Studio 서버가 켜져 있어야 합니다.
- FastAPI 실행은 `python3 -m uvicorn api.main:app --port 8000`
- ARQ 워커 실행은 `arq workers.arq_worker.WorkerSettings`
- 웹 개발 서버 실행은 `cd ../../apps/web && npm run dev`
- 크롤링/적재 실행은 `python3 -m pipelines.ingest`
- LMS 동기화 실행은 `python3 -m sync.lms_sync`
- KNUIS 동기화 실행은 `python3 -m sync.knuis_sync`
