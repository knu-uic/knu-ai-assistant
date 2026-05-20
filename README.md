# KNU AI Assistant

공주대학교 공지와 학과 자료를 크롤링해 PostgreSQL/pgvector에 저장하고, Streamlit 공지 보드와 LangGraph 기반 RAG 챗봇으로 제공하는 학생 맞춤형 안내 서비스입니다.

## 현재 기능

- 공주대학교 일반 공지 크롤링
- 컴퓨터공학과 학과공지 크롤링
- 컴퓨터공학과 교과과정표 PDF 결정론적 파싱
- 본문 이미지 OCR, 이미지/PDF/HWPX/XLSX 첨부 텍스트 추출
- LLM 기반 `summary`, `category`, `target`, `start_date`, `end_date`, `keywords` 생성
- 원문 `content` 보존 및 청크 임베딩 저장
- 카테고리별 물리 테이블과 pgvector HNSW 검색
- BGE reranker 기반 top-3 문서 재정렬
- 답변 생성 및 verifier를 포함한 LangGraph RAG 파이프라인
- 사용자 학과/관심사 기반 홈 추천과 공지 목록

## 구조

```text
.
├── app.py                         # Streamlit 진입점
├── app_pages/                     # 홈, 공지, 챗봇, 프로필 페이지
├── attachments.py                 # 첨부파일/본문 이미지 텍스트 추출
├── crawlers/
│   ├── registry.py                # 크롤러 등록
│   ├── crawltest/crawl_one.py     # 단일 URL 테스트 리포트 생성
│   ├── methods/                   # 공통 크롤러 구현
│   └── sites/                     # 사이트/학과별 크롤러 설정
├── curriculum_parser.py           # 교과과정표 PDF 파서
├── db.py                          # DB 스키마, 저장, 검색
├── embed.py                       # 청킹 및 임베딩
├── graph.py                       # LangGraph RAG
├── main.py                        # 전체 크롤링/적재 배치
├── model.py                       # LLM/Embedding/Reranker 설정
├── refine.py                      # LLM 메타데이터/요약 정제
├── schema.py                      # 구조화 출력 스키마
└── rerank.py                      # BGE reranker 래퍼
```

## 데이터 흐름

```text
크롤러
→ 본문 텍스트 + 본문 이미지 OCR + 첨부파일 추출 텍스트 생성
→ refine.py에서 summary/category/target/date/keywords 생성
→ document_* 테이블에 원문 content와 summary 저장
→ embed.py에서 title + content 청킹 및 임베딩
→ document_*_chunk 테이블에 vector(768) 저장
→ graph.py에서 router → retriever → reranker → answerer → verifier 실행
```

`summary`는 UI/컨텍스트 압축용 보조 데이터입니다. 검색 임베딩과 최종 근거는 계속 원문 `content`를 기준으로 합니다.

## 데이터베이스

PostgreSQL 16 + pgvector를 사용합니다.

문서는 카테고리별 테이블에 저장됩니다.

```text
document_scholarship
document_academic
document_career
document_event
document_etc
```

각 문서 테이블의 핵심 컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `source_id` | `source.id` 참조 |
| `url` | 원문 URL, unique |
| `title` | 제목 |
| `content` | 원문 본문 + OCR + 첨부 추출 텍스트 |
| `summary` | LLM 요약 |
| `posted_at` | 게시글 등록일 |
| `start_date`, `end_date` | 접수/행사 기간 |
| `is_pinned` | 게시판 고정 공지 보존 플래그 |
| `target` | 학과/학년/학적 대상 |
| `keywords` | 추천/필터용 키워드 |
| `extra` | 교과과정표 등 구조화 부가 JSON |

각 카테고리에는 별도 chunk 테이블이 있습니다.

```text
document_scholarship_chunk
document_academic_chunk
document_career_chunk
document_event_chunk
document_etc_chunk
```

chunk 테이블은 `embedding vector(768)`과 HNSW cosine index를 사용합니다.

첨부/본문 이미지는 통합 `document_asset` 테이블에 저장합니다. 현재 검색은 `document_asset`을 직접 보지 않고, 추출 텍스트가 `document.content`에 붙은 뒤 청킹되어 검색됩니다.

## 문서 정리 정책

`main.py`는 더 이상 DB를 전체 초기화하지 않습니다.

실행 시:

1. `init_db()`로 스키마를 비파괴 준비
2. 현재 게시판의 고정 공지 URL 수집
3. `is_pinned` 동기화
4. 최근 6개월보다 오래됐거나 마감된 문서 삭제
5. 이미 DB에 있는 URL은 상세 크롤링/OCR 생략
6. 신규 문서만 저장 및 임베딩

고정 공지는 6개월이 지나도 삭제되지 않습니다.

## 첨부파일 처리

| 형식 | 처리 |
| --- | --- |
| 본문 이미지 | 이미지 다운로드 후 VLM OCR, `inline_image` asset 저장 |
| 이미지 첨부 | VLM OCR, 원본 이미지 sha1 파일 저장 |
| PDF | `pdfplumber` 텍스트 추출, 텍스트가 없으면 `pdf2image` + VLM OCR |
| HWPX | synapView 미리보기 또는 ZIP XML 파싱 |
| HWP | synapView 미리보기 시도, 바이너리 직접 파싱은 미지원 |
| XLSX | `openpyxl`로 전체 추출, 표 헤더 보존 |
| XLS | openpyxl 미지원으로 안내문만 저장 |
| ZIP/기타 | 안내문 저장, 내부 파일 파싱은 미구현 |

XLSX는 행마다 헤더를 반복하지 않고 `[표 헤더]`, `[행]` 형식으로 저장합니다. 청킹 중 표가 잘리면 `embed.py`가 현재 시트/헤더를 청크 앞에 보강합니다.

## RAG 검색/답변

1. router가 질문 카테고리와 검색용 확장 질의를 생성합니다.
2. `search_chunks()`가 카테고리별 chunk 테이블에서 문서당 대표 청크를 찾습니다.
3. BGE reranker가 후보 15개를 재정렬해 top 3 문서를 선택합니다.
4. 1순위 문서는 가능한 한 원문 전체를 넣습니다.
5. 컨텍스트가 부족하면 1순위 문서를 우선 보존하고, 2~3순위는 `summary + matched_chunk + 첨부파일명` 중심으로 넣습니다.
6. answerer가 컨텍스트 기반 답변을 생성합니다.
7. verifier가 답변 충실도를 검증합니다.

## 환경변수

`.env` 예시:

```bash
DB_PASSWORD=your_db_password
DB_USER=knu-uic
DB_NAME=knu-uic
DB_HOST=localhost
DB_PORT=5432

VLM_PROVIDER=lmstudio
EMBEDDING_PROVIDER=lmstudio
LLM_MODEL=gemma-4-e4b
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
LMSTUDIO_BASE_URL=http://localhost:1234/v1

GOOGLE_API_KEY=
GEMINI_API_KEY=

LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=knu-ai-assistant
```

`VLM_PROVIDER`와 `EMBEDDING_PROVIDER`는 `lmstudio` 또는 `google`을 사용할 수 있습니다. 현재 기본값은 LM Studio입니다.

Docker Compose에서 앱 컨테이너가 호스트의 LM Studio에 접근할 때는 기본값으로 `http://host.docker.internal:1234/v1`을 사용합니다.

## 로컬 실행

PostgreSQL/pgvector만 Docker로 띄우고 앱은 로컬에서 실행하는 방식입니다.

```bash
docker compose up -d db

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium

python3 main.py
streamlit run app.py
```

스캔 PDF OCR을 쓰려면 로컬에도 poppler가 필요합니다.

macOS:

```bash
brew install poppler
```

## Docker 실행

```bash
docker compose up --build
```

앱:

```text
http://localhost:8501
```

컨테이너 안에서 크롤링/적재:

```bash
docker compose exec app python main.py
```

## 단일 URL 테스트

DB 저장 없이 특정 공지 하나만 크롤링하고 txt 리포트를 만들 수 있습니다.

```bash
python3 crawlers/crawltest/crawl_one.py "https://www.kongju.ac.kr/bbs/KNU/2132/427500/artclView.do?layout=unknown"
```

결과는 기본적으로 여기에 저장됩니다.

```text
crawl_result/reports/
```

리포트에는 크롤링 결과, asset OCR/첨부 추출 결과, LLM refine 결과, embedding chunk가 포함됩니다. DB에는 저장하지 않습니다.

## 크롤러 추가

학과 게시판을 추가할 때는 `crawlers/sites/departments/`에 설정을 추가하고 `crawlers/registry.py`에 등록합니다.

학과 추천은 `source.department`와 사용자 프로필의 `major`를 비교합니다.

```sql
s.department = :major
OR :major = ANY(d.target)
OR '전체' = ANY(d.target)
```

따라서 학과 게시판 크롤러의 `department` 값을 정확히 넣는 것이 중요합니다.

## 검증 명령

```bash
python3 -m py_compile \
  app.py main.py db.py model.py refine.py schema.py embed.py graph.py rerank.py \
  attachments.py curriculum_parser.py ui.py \
  crawlers/registry.py crawlers/methods/*.py crawlers/sites/*.py \
  crawlers/sites/departments/*.py crawlers/crawltest/crawl_one.py
```

requirements 파일 문법 확인:

```bash
python3 -m pip install --dry-run -r requirements.txt
```

## 주의사항

- 기존 DB에 이미 들어간 문서는 새 `summary` 컬럼이 비어 있을 수 있습니다. 재크롤링 또는 백필이 필요합니다.
- `.xls`, `.zip`은 현재 실질 내용 파싱 대상이 아닙니다.
- `document_asset.extracted_text`는 디버깅/재처리용이고, 검색은 `document.content`에서 만들어진 chunk를 사용합니다.
- Docker에서 LM Studio를 쓰려면 호스트 LM Studio 서버가 켜져 있어야 합니다.
