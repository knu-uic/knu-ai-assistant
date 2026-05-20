# Graph Report - knu_ai_assistant  (2026-05-20)

## Corpus Check
- 48 files · ~24,076 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 700 nodes · 824 edges · 76 communities (62 shown, 14 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 85 edges (avg confidence: 0.83)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `418546ac`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Document Parser|Document Parser]]
- [[_COMMUNITY_Project Documentation|Project Documentation]]
- [[_COMMUNITY_CSE & Control Curriculum|CSE & Control Curriculum]]
- [[_COMMUNITY_LangGraph RAG Pipeline|LangGraph RAG Pipeline]]
- [[_COMMUNITY_DB Schema & Queries|DB Schema & Queries]]
- [[_COMMUNITY_Project State Notes|Project State Notes]]
- [[_COMMUNITY_Curriculum Parser (VLM)|Curriculum Parser (VLM)]]
- [[_COMMUNITY_Semiconductor Curriculum|Semiconductor Curriculum]]
- [[_COMMUNITY_User Profile|User Profile]]
- [[_COMMUNITY_Board Notice Crawler|Board Notice Crawler]]
- [[_COMMUNITY_Curriculum Ingest Script|Curriculum Ingest Script]]
- [[_COMMUNITY_Embedding Module|Embedding Module]]
- [[_COMMUNITY_Home Page UI|Home Page UI]]
- [[_COMMUNITY_Reranker|Reranker]]
- [[_COMMUNITY_Claude Settings|Claude Settings]]
- [[_COMMUNITY_Static Page Crawler|Static Page Crawler]]
- [[_COMMUNITY_App Entry|App Entry]]
- [[_COMMUNITY_Main Crawl Entry|Main Crawl Entry]]
- [[_COMMUNITY_HWPX Tests|HWPX Tests]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Chatbot Page|Chatbot Page]]
- [[_COMMUNITY_Notices Page|Notices Page]]
- [[_COMMUNITY_Profile Page|Profile Page]]
- [[_COMMUNITY_Gemini Provider Notes|Gemini Provider Notes]]
- [[_COMMUNITY_Config|Config]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_langchain-core dep|langchain-core dep]]
- [[_COMMUNITY_langchain-community dep|langchain-community dep]]
- [[_COMMUNITY_langchain-postgres dep|langchain-postgres dep]]
- [[_COMMUNITY_OpenAI Provider Notes|OpenAI Provider Notes]]
- [[_COMMUNITY_General Education Cat|General Education Cat]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 75|Community 75]]

## God Nodes (most connected - your core abstractions)
1. `KNU AI Assistant project` - 24 edges
2. `KNU AI Assistant` - 23 edges
3. `ingest()` - 17 edges
4. `insert_chunks()` - 15 edges
5. `insert_document()` - 14 edges
6. `search_chunks()` - 13 edges
7. `stack_summary` - 12 edges
8. `_search_subquery()` - 11 edges
9. `get_document_content()` - 11 edges
10. `_list_subquery()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `KNU AI Assistant project spec` --semantically_similar_to--> `KNU AI Assistant project`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `Integrated RAG chatbot feature` --semantically_similar_to--> `RAG query pipeline (graph.py)`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `_iter_documents()` --calls--> `_doc_ident()`  [INFERRED]
  scripts/rechunk.py → db.py
- `stage_db()` --calls--> `reset_db()`  [INFERRED]
  scripts/smoke_offline.py → db.py
- `ingest()` --calls--> `upsert_source()`  [INFERRED]
  scripts/ingest_curriculum_local.py → db.py

## Hyperedges (group relationships)
- **RAG query pipeline nodes** — claudemd_node_router, claudemd_node_retrieve, claudemd_node_answerer, claudemd_node_verifier [EXTRACTED 1.00]
- **Retrieval stack: pgvector HNSW + BGE reranker + provider embeddings** — claudemd_pgvector_hnsw, claudemd_bge_reranker, claudemd_llm_provider_openai, claudemd_llm_provider_gemini [INFERRED 0.95]
- **Docker stack: app + db + pgdata + bot_network** — docker_compose_app_service, docker_compose_db_service, docker_compose_pgdata_volume, docker_compose_bot_network [EXTRACTED 1.00]
- **공과대학 departments with curricula** — curriculums_mae_department, curriculums_cse_department, curriculums_eec_department [EXTRACTED 1.00]
- **기계설계공학전공 curriculum year cohorts** — curriculums_mae_design_2011, curriculums_mae_design_2012_to_2016, curriculums_mae_design_2017_to_2019, curriculums_mae_design_2020, curriculums_mae_design_2021, curriculums_mae_design_2025 [EXTRACTED 1.00]
- **기계공학전공 curriculum year cohorts** — curriculums_mae_mech_2011_to_2014, curriculums_mae_mech_2015_to_2016, curriculums_mae_mech_2020, curriculums_mae_mech_2021_to_2024, curriculums_mae_mech_2025, curriculums_mae_mech_2026_to_2029 [EXTRACTED 1.00]
- **5 RAG categories** — claudemd_category_taxonomy [EXTRACTED 1.00]
- **전기전자제어공학부 산하 전공들** — jeongi_jeonja_jeoeo_dept, jeongigonghak_major, bandoche_jeongbo_major, jeonjagonghak_major [EXTRACTED 1.00]
- **전기공학전공 학년도별 교과과정** — jeongigonghak_major, jeongigonghak_ee_electrical_2011_to_2016, jeongigonghak_ee_electrical_2017_to_2020, jeongigonghak_ee_electrical_2021_to_2024, jeongigonghak_ee_electrical_2025, jeongigonghak_ee_electrical_2026 [EXTRACTED 1.00]
- **반도체정보공학전공 학년도별 교과과정** — bandoche_jeongbo_major, bandoche_jeongbo_ee_semiconductor_2015_to_2016, bandoche_jeongbo_ee_semiconductor_2017_to_2018, bandoche_jeongbo_ee_semiconductor_2019_to_2020, bandoche_jeongbo_ee_semiconductor_2021_to_2022, bandoche_jeongbo_ee_semiconductor_2023_to_2026 [EXTRACTED 1.00]
- **전자공학전공 학년도별 교과과정** — jeonjagonghak_major, jeonjagonghak_ee_electronics_2014_to_2020, jeonjagonghak_ee_electronics_2021_to_2024, jeonjagonghak_ee_electronics_2021_to_2025, jeonjagonghak_ee_electronics_2026 [EXTRACTED 1.00]
- **교과과정 공통 분류 체계** — course_category_major_required, course_category_major_elective, course_category_general [INFERRED 0.85]

## Communities (76 total, 14 thin omitted)

### Community 0 - "Document Parser"
Cohesion: 0.07
Nodes (40): AssetMeta, attachment_to_text(), _detect_header_row_index(), _detect_image_mime_from_magic(), _download(), _handle_hwp_family(), _handle_image_attachment(), _handle_pdf() (+32 more)

### Community 1 - "Project Documentation"
Cohesion: 0.07
Nodes (38): BAAI/bge-reranker-v2-m3 (CPU, OMP_NUM_THREADS=8), Category taxonomy: 장학/등록, 학사/수업, 진로/취업, 행사/공모전, 일반/기타, Crawl pipeline (main.py -> crawlers -> attachments -> refine -> db), LangSmith @traceable decorator on RAG nodes, answerer node (LLM answer from fulldoc context), _retrieve node (HNSW + rerank + dedupe + fulldoc), router node (intent + categories + expanded_query), verifier node (VerificationResult) (+30 more)

### Community 2 - "CSE & Control Curriculum"
Cohesion: 0.06
Nodes (34): 교양 (Liberal Arts / General Education courses), 전공선택 (Major Elective courses), 전공필수 (Major Required courses), 컴퓨터공학과 2011~2026학년도 교과과정, 컴퓨터공학과 (Department of Computer Engineering), 제어계측공학 2015~2026학년도 교과과정, 제어계측공학전공 (Control & Instrumentation Engineering major), 전기전자제어공학부 (School of Electrical, Electronic and Control Engineering) (+26 more)

### Community 3 - "LangGraph RAG Pipeline"
Cohesion: 0.05
Nodes (44): BaseModel, answerer_node(), casual_answerer_node(), ChatState, _format_context(), _history_messages(), LangGraph: 라우터(분류+쿼리확장) → retriever → answerer → verifier 4노드 RAG 파이프라인., history dict 리스트를 LangChain Human/AI 메시지로 변환. (+36 more)

### Community 4 - "DB Schema & Queries"
Cohesion: 0.19
Nodes (12): _chunk_ident(), _doc_ident(), document_exists(), 5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단., 5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단., 5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단., 5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단., 5개 category 테이블 중 어디든 url이 있으면 True. 카테고리 간 url 중복은 application level에서 차단. (+4 more)

### Community 5 - "Project State Notes"
Cohesion: 0.06
Nodes (30): completed_in_recent_sessions, deferred_known_issues, last_updated, next_round_candidates, pending_code_changes, items, plan_file, scope_agreed (+22 more)

### Community 6 - "Curriculum Parser (VLM)"
Cohesion: 0.10
Nodes (26): main(), 실행 방법:   docker compose exec app python check_pdf.py, _is_no_table(), _page_to_year(), parse(), 학과 교육과정표 PDF → VLM 기반 범용 마크다운 표 추출.  정책 (2026-05-18 도입): - 학과별 표 양식이 다양해서 결정론 파서, parse() 결과의 한 year를 RAG 본문 텍스트로 직렬화.     VLM이 만들어준 markdown_table을 그대로 반환 (inges, VLM 응답의 `[YEAR: ...]` prefix를 떼어내 (year_label, markdown_table) 반환.     prefix 없거 (+18 more)

### Community 7 - "Semiconductor Curriculum"
Cohesion: 0.18
Nodes (16): 반도체정보공학전공 2015~2016학년도 교과과정, 반도체정보공학전공 2017~2018학년도 교과과정, 반도체정보공학전공 2019~2020학년도 교과과정, 반도체정보공학전공 2021~2022학년도 교과과정, 반도체정보공학전공 2023~2026학년도 교과과정, 전공선택, 전공필수, 전기공학전공 2011~2016학년도 교과과정 (+8 more)

### Community 8 - "User Profile"
Cohesion: 0.07
Nodes (27): get_user(), users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다., users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다., users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다., users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다., profile UPSERT. interests는 콤마 문자열로 저장., profile UPSERT. interests는 콤마 문자열로 저장., profile UPSERT. interests는 콤마 문자열로 저장. (+19 more)

### Community 9 - "Board Notice Crawler"
Cohesion: 0.24
Nodes (4): BoardNoticeConfig, BoardNoticeCrawler, 제목·본문 등을 합쳐 XLSX_KEYWORDS 중 하나라도 포함하면 True., xlsx_relevant()

### Community 10 - "Curriculum Ingest Script"
Cohesion: 0.11
Nodes (25): chunk_text(), embed_chunks(), embed_query(), get_embeddings(), _get_splitter(), provider 토글에 따라 OpenAI/Gemini 임베딩 클라이언트를 돌려준다.      두 provider 모두 결과 차원을 EMBEDDI, RecursiveCharacterTextSplitter 싱글톤. lazy import로 cold start 영향 회피., 한국어 공지 기준 의미 단위 분할. CHUNK_SIZE 자 상한, CHUNK_OVERLAP 자 overlap. (+17 more)

### Community 11 - "Embedding Module"
Cohesion: 0.08
Nodes (24): 4.1 스마트 공지사항 보드, 4.2 통합 지능형 챗봇, 4.3 데이터 수집 및 메타데이터 정제, 4.4 첨부파일 처리, 4.5 컴퓨터공학과 교과과정표 처리, 4. 핵심 기능 명세, code:sql (s.department = :major), 개인화 노출 규칙 (+16 more)

### Community 12 - "Home Page UI"
Cohesion: 0.38
Nodes (6): _d_label(), 홈 페이지. 관심사·학과 기반 추천 3건 + 마감 임박 공지., 관심키워드 매칭 + 학과 일치 + 마감 임박도로 점수 산출.      임베딩 호출 없이 결정적으로 동작. 반환: (score, matched_k, _render_deadline_row(), _render_recommendation_card(), _score_notice()

### Community 13 - "Reranker"
Cohesion: 0.10
Nodes (18): 1. Think Before Coding, 2. Simplicity First, 3. Surgical Changes, 4. Goal-Driven Execution, 5. Test-Driven Development (TDD), code:block1 (1. [Step] → verify: [check]), code:block2 (app.py                          Streamlit 진입점 (페이지 네비, reran), code:bash (# 컨테이너 기동 / 재기동) (+10 more)

### Community 14 - "Claude Settings"
Cohesion: 0.40
Nodes (4): permissions, allow, worktree, bgIsolation

### Community 18 - "HWPX Tests"
Cohesion: 0.21
Nodes (12): _embed_with_retry(), _iter_documents(), main(), _process_one(), DB document_*만으로 청크/임베딩 재생성. 크롤링 우회.  용도: CHUNK_SIZE / CHUNK_OVERLAP / 임베딩 정책 변경, 한글 카테고리 또는 영문 slug 입력 정규화., document_{slug} 전수 또는 단건 SELECT 제너레이터., exponential backoff 4회. 모든 예외 retry — auth 같은 영구 에러도 최대 7s 낭비 허용. (+4 more)

### Community 19 - "Community 19"
Cohesion: 0.29
Nodes (7): 11.1 기능 목적, 11.2 주요 기능, 11.3 문제 생성 정책, 11.4 예상 처리 흐름, 11.5 검수와 품질 관리, 11. AI 학습 보조 및 문제은행 확장 명세, code:mermaid (flowchart LR)

### Community 25 - "Community 25"
Cohesion: 0.14
Nodes (14): 8.1 데이터베이스 선택, 8.2 테이블 개요, 8.3 `source`, 8.4 `document`, 8.5 `document_asset`, 8.6 `document_chunk`, 8.7 `users`, 8.8 향후 문제은행 확장 테이블 제안 (+6 more)

### Community 47 - "Community 47"
Cohesion: 0.15
Nodes (13): 7.1 배치 처리 흐름, 7.2 크롤러 공통 상수, 7.3 크롤러 반환 스키마, 7.4 자산 메타데이터 스키마, 7.5 LLM 메타데이터 정제 스키마, 7.6 target 추출 규칙, 7.7 청크화 및 임베딩 정책, 7. 데이터 파이프라인 명세 (+5 more)

### Community 48 - "Community 48"
Cohesion: 0.18
Nodes (11): 10.1 현재 화면 구조, 10.2 사이드바, 10.3 공지사항 게시판 탭, 10.4 AI 챗봇 탭, 10.5 사용자 경험 요구사항, 10. 웹앱 UI 명세, code:text (사이드바), 목록 표시 요소 (+3 more)

### Community 49 - "Community 49"
Cohesion: 0.18
Nodes (11): 15.1 벡터 DB 정책, 15.2 통합 테이블 정책, 15.3 JSONB 확장 정책, 15.4 정형 데이터 처리 정책, 15.5 본문 보존 정책, 15.6 크롤러 추가 절차, 15.7 오류 처리 원칙, 15. 개발 컨벤션 (+3 more)

### Community 50 - "Community 50"
Cohesion: 0.22
Nodes (9): 14.1 Docker Compose 실행, 14.2 초기 데이터 수집, 14.3 로컬 개발 실행, 14.4 데이터 갱신 운영 방식, 14. 설치 및 실행 방법, code:bash (docker compose up --build), code:text (http://localhost:8501), code:bash (docker compose exec app python main.py) (+1 more)

### Community 51 - "Community 51"
Cohesion: 0.25
Nodes (8): 18.1 개발 우선순위, 18.2 단계별 계획, 18.3 완료된 세부 작업, 18.4 남은 세부 작업, 18. 로드맵, Phase 1. 데이터 파이프라인 및 웹앱 뼈대 구축, Phase 2. RAG 챗봇 고도화 및 학습 자료 처리, Phase 3. 문제은행 게시판 및 라우팅 에이전트

### Community 52 - "Community 52"
Cohesion: 0.25
Nodes (7): 20.1 MVP 산출물, 20.2 최종 시연 산출물, 20.3 성공 기준, 20. 최종 산출물 정의, KNU AI Assistant, 목차, 문서 정보

### Community 53 - "Community 53"
Cohesion: 0.29
Nodes (7): 19.1 포털 HTML 구조 변경, 19.2 LLM 메타데이터 오류, 19.3 OCR 비용과 지연, 19.4 벡터 검색 품질, 19.5 개인정보와 저작권, 19.6 운영 DB 마이그레이션, 19. 리스크와 대응 전략

### Community 54 - "Community 54"
Cohesion: 0.29
Nodes (7): 5.1 전체 구조, 5.2 계층별 책임, 5.3 2-Phase 아키텍처, 5.4 향후 서비스 분리 구조, 5. 시스템 아키텍처, code:mermaid (flowchart LR), code:mermaid (flowchart TB)

### Community 55 - "Community 55"
Cohesion: 0.29
Nodes (7): 9.1 검색 흐름, 9.2 벡터 검색 쿼리 특성, 9.3 답변 생성 프롬프트 정책, 9.4 할루시네이션 방지 전략, 9.5 검색 품질 개선 후보, 9. RAG 검색 및 답변 생성 명세, code:mermaid (sequenceDiagram)

### Community 56 - "Community 56"
Cohesion: 0.33
Nodes (6): 12.1 도입 목적, 12.2 라우팅 대상, 12.3 LangGraph 노드 제안, 12.4 Verifier 역할, 12. 라우팅 에이전트 확장 명세, code:mermaid (flowchart TD)

### Community 57 - "Community 57"
Cohesion: 0.33
Nodes (6): 13.1 언어 및 런타임, 13.2 주요 라이브러리, 13.3 인프라 구성, 13.4 환경변수, 13. 기술 스택과 실행 환경, code:bash (DB_PASSWORD=your_database_password)

### Community 58 - "Community 58"
Cohesion: 0.33
Nodes (6): 1.1 한 줄 정의, 1.2 프로젝트 목표, 1.3 핵심 가치, 1.4 현재 구현 범위, 1.5 현재 미구현 또는 확장 예정 범위, 1. 프로젝트 개요

### Community 59 - "Community 59"
Cohesion: 0.40
Nodes (5): 16.1 기능 검증 기준, 16.2 RAG 품질 평가 지표, 16.3 수동 테스트 시나리오, 16.4 자동화 테스트 후보, 16. 품질 기준과 검증 계획

### Community 60 - "Community 60"
Cohesion: 0.40
Nodes (5): 17.1 공공 데이터 처리, 17.2 사용자 프로필 데이터, 17.3 업로드 학습 자료, 17.4 API 키 관리, 17. 보안, 개인정보, 데이터 거버넌스

### Community 61 - "Community 61"
Cohesion: 0.40
Nodes (5): 6.1 파일 구조, 6.2 모듈별 상세 역할, 6.3 현재 데이터 소스, 6. 현재 구현 모듈, code:text (.)

### Community 62 - "Community 62"
Cohesion: 0.38
Nodes (6): main(), LLM/VLM/embedding 한 번도 호출하지 않는 main+crawler 회로 스모크.  용도: 본 크롤 진입 전 schema·signat, 가짜 데이터로 schema·DB 회로 검증. LLM/embedding 호출 0., LLM-차단 monkeypatch 후 실제 static_page 크롤러 1건만 yield 확인.      `crawlers.methods.boa, stage_crawler(), stage_db()

### Community 64 - "Community 64"
Cohesion: 0.50
Nodes (4): _connect_with_vector(), pgvector 어댑터가 등록된 커넥션을 돌려준다 (vector 컬럼 쓰는 쿼리 전용)., pgvector 어댑터가 등록된 커넥션을 돌려준다 (vector 컬럼 쓰는 쿼리 전용)., pgvector 어댑터가 등록된 커넥션을 돌려준다 (vector 컬럼 쓰는 쿼리 전용).

### Community 65 - "Community 65"
Cohesion: 0.09
Nodes (23): ensure_users_schema(), get_documents(), _list_subquery(), get_documents용 카테고리 단위 서브쿼리., get_documents용 카테고리 단위 서브쿼리., get_documents용 카테고리 단위 서브쿼리., document_{slug} + source join. category None이면 5개 UNION ALL.      반환 튜플:     (ur, document_{slug} + source join. category None이면 5개 UNION ALL.      반환 튜플:     (ur (+15 more)

### Community 66 - "Community 66"
Cohesion: 0.25
Nodes (8): insert_document(), category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환., category에 해당하는 document_{slug} 테이블에 UPSERT 후 id 반환.

### Community 67 - "Community 67"
Cohesion: 0.14
Nodes (15): 카테고리 하나에 대한 청크 단위 서브쿼리 Composable.      placeholder 순서: [vec, (major, major)?, (, 카테고리 하나에 대한 청크 단위 서브쿼리 Composable.      placeholder 순서: [vec, (major, major)?, (, 카테고리 하나에 대한 청크 단위 서브쿼리 Composable.      placeholder 순서: [vec, (major, major)?, (, 카테고리 하나에 대한 청크 단위 서브쿼리 Composable.      placeholder 순서: [vec, (major, major)?, (, HNSW 코사인 유사도 검색. 청크 단위로 score 상위 N개 반환 (문서 중복 허용).      categories: 검색 대상 카테고리 리, HNSW 코사인 유사도 검색. 청크 단위로 score 상위 N개 반환 (문서 중복 허용).      categories: 검색 대상 카테고리 리, HNSW 코사인 유사도 검색. 청크 단위로 score 상위 N개 반환 (문서 중복 허용).      categories: 검색 대상 카테고리 리, 카테고리 하나에 대한 청크 단위 서브쿼리 Composable.      placeholder 순서: [vec, (major, major)?, ( (+7 more)

### Community 68 - "Community 68"
Cohesion: 0.29
Nodes (7): 3.1 주요 사용자, 3.2 대표 사용자 시나리오, 3. 사용자와 활용 시나리오, 시나리오 A: 맞춤형 공지 확인, 시나리오 B: 자연어 공지 검색, 시나리오 C: 교과과정 질의, 시나리오 D: 수업 자료 기반 예상 문제 생성

### Community 69 - "Community 69"
Cohesion: 0.17
Nodes (13): insert_assets(), insert_chunks(), category에 해당하는 document_{slug}_chunk에 일괄 저장.      chunks: [(chunk_idx, content,, category에 해당하는 document_{slug}_chunk에 일괄 저장.      chunks: [(chunk_idx, content,, category에 해당하는 document_{slug}_chunk에 일괄 저장.      chunks: [(chunk_idx, content,, document_asset(통합)에 일괄 저장. (category, document_id) 키로 기존 자산 삭제 후 재삽입., document_asset(통합)에 일괄 저장. (category, document_id) 키로 기존 자산 삭제 후 재삽입., category에 해당하는 document_{slug}_chunk에 일괄 저장.      chunks: [(chunk_idx, content, (+5 more)

### Community 70 - "Community 70"
Cohesion: 0.25
Nodes (8): get_document_content(), url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용., url로 document 전체 content 조회. small-to-big용 — academic 소스처럼 표가 통째로 필요할 때 사용.

### Community 71 - "Community 71"
Cohesion: 0.50
Nodes (4): 2.1 문제 정의, 2.2 해결 방향, 2.3 기존 방식 대비 차별점, 2. 문제 정의와 해결 방향

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (6): delete_document_by_url(), URL로 5개 category 테이블을 훑어 일치하는 문서·청크를 삭제.      chunks는 FK ON DELETE CASCADE로 자동 정, URL로 5개 category 테이블을 훑어 일치하는 문서·청크를 삭제.      chunks는 FK ON DELETE CASCADE로 자동 정, URL로 5개 category 테이블을 훑어 일치하는 문서·청크·자산을 삭제.      chunks는 FK ON DELETE CASCADE로 자, URL로 5개 category 테이블을 훑어 일치하는 문서·청크를 삭제.      chunks는 FK ON DELETE CASCADE로 자동 정, URL로 5개 category 테이블을 훑어 일치하는 문서·청크·자산을 삭제.      chunks는 FK ON DELETE CASCADE로 자

### Community 73 - "Community 73"
Cohesion: 0.29
Nodes (7): _normalize_date(), LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과., LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과., LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과., LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과., LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과., LLM이 'null'/'미정' 같은 sentinel 문자열을 반환해도 None으로 흡수.      date/datetime 객체는 그대로 통과.

### Community 75 - "Community 75"
Cohesion: 0.14
Nodes (17): source 테이블에 UPSERT 후 id 반환., source 테이블에 UPSERT 후 id 반환., source 테이블에 UPSERT 후 id 반환., source 테이블에 UPSERT 후 id 반환., upsert_source(), _embed_with_prefix(), _extract_text(), _fallback_split() (+9 more)

## Knowledge Gaps
- **198 isolated node(s):** `project`, `working_directory`, `last_updated`, `vector_db`, `embedding` (+193 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ingest()` connect `Curriculum Ingest Script` to `Community 66`, `Community 75`, `Community 69`, `Curriculum Parser (VLM)`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `ingest_one()` connect `Community 75` to `Document Parser`, `Community 66`, `Community 69`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `KNU AI Assistant` connect `Community 52` to `Embedding Module`, `Community 19`, `Community 25`, `Community 47`, `Community 48`, `Community 49`, `Community 50`, `Community 51`, `Community 53`, `Community 54`, `Community 55`, `Community 56`, `Community 57`, `Community 58`, `Community 59`, `Community 60`, `Community 61`, `Community 68`, `Community 71`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `ingest()` (e.g. with `parse()` and `upsert_source()`) actually correct?**
  _`ingest()` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `insert_chunks()` (e.g. with `ingest()` and `ingest_one()`) actually correct?**
  _`insert_chunks()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `insert_document()` (e.g. with `ingest()` and `ingest_one()`) actually correct?**
  _`insert_document()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `BGE-reranker 로컬 cross-encoder 재정렬.  graph.py의 _retrieve에서 vector top-N 후보를 받아 to`, `앱 부팅 시 호출. 모델 로드 + 더미 forward 1회로 첫 질문 latency 제거.`, `각 passage의 relevance score 리스트 반환 (입력 순서 유지, sigmoid로 0~1 정규화).` to the rest of the system?**
  _396 weakly-connected nodes found - possible documentation gaps or missing edges._