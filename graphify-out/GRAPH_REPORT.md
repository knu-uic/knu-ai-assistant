# Graph Report - knu_ai_assistant  (2026-05-19)

## Corpus Check
- 48 files · ~23,578 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 381 nodes · 476 edges · 47 communities (32 shown, 15 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.83)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c779a73d`
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
- [[_COMMUNITY_SynapView Tests|SynapView Tests]]
- [[_COMMUNITY_Chatbot Page|Chatbot Page]]
- [[_COMMUNITY_Notices Page|Notices Page]]
- [[_COMMUNITY_Profile Page|Profile Page]]
- [[_COMMUNITY_Gemini Provider Notes|Gemini Provider Notes]]
- [[_COMMUNITY_Config|Config]]
- [[_COMMUNITY_langchain-core dep|langchain-core dep]]
- [[_COMMUNITY_langchain-community dep|langchain-community dep]]
- [[_COMMUNITY_langchain-postgres dep|langchain-postgres dep]]
- [[_COMMUNITY_OpenAI Provider Notes|OpenAI Provider Notes]]
- [[_COMMUNITY_General Education Cat|General Education Cat]]

## God Nodes (most connected - your core abstractions)
1. `KNU AI Assistant project` - 24 edges
2. `ingest()` - 13 edges
3. `stack_summary` - 12 edges
4. `BoardNoticeCrawler` - 10 edges
5. `parse()` - 9 edges
6. `RAG query pipeline (graph.py)` - 9 edges
7. `_doc_ident()` - 8 edges
8. `attachment_to_text()` - 8 edges
9. `_retrieve()` - 7 edges
10. `_slug()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `KNU AI Assistant project spec` --semantically_similar_to--> `KNU AI Assistant project`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `Integrated RAG chatbot feature` --semantically_similar_to--> `RAG query pipeline (graph.py)`  [INFERRED] [semantically similar]
  README.md → CLAUDE.md
- `ingest()` --calls--> `embed_chunks()`  [INFERRED]
  scripts/ingest_curriculum_local.py → embed.py
- `_retrieve()` --calls--> `embed_query()`  [INFERRED]
  graph.py → embed.py
- `_vector_search()` --calls--> `search_chunks()`  [INFERRED]
  graph.py → db.py

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

## Communities (47 total, 15 thin omitted)

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
Cohesion: 0.09
Nodes (29): BaseModel, answerer_node(), casual_answerer_node(), ChatState, _format_context(), _history_messages(), LangGraph: 라우터(분류+쿼리확장) → retriever → answerer → verifier 4노드 RAG 파이프라인., history dict 리스트를 LangChain Human/AI 메시지로 변환. (+21 more)

### Community 4 - "DB Schema & Queries"
Cohesion: 0.10
Nodes (31): _chunk_ident(), _connect_with_vector(), delete_document_by_url(), _doc_ident(), document_exists(), ensure_users_schema(), get_document_content(), get_documents() (+23 more)

### Community 5 - "Project State Notes"
Cohesion: 0.06
Nodes (30): completed_in_recent_sessions, deferred_known_issues, last_updated, next_round_candidates, pending_code_changes, items, plan_file, scope_agreed (+22 more)

### Community 6 - "Curriculum Parser (VLM)"
Cohesion: 0.10
Nodes (25): main(), _is_no_table(), _page_to_year(), parse(), 학과 교육과정표 PDF → VLM 기반 범용 마크다운 표 추출.  정책 (2026-05-18 도입): - 학과별 표 양식이 다양해서 결정론 파서, parse() 결과의 한 year를 RAG 본문 텍스트로 직렬화.     VLM이 만들어준 markdown_table을 그대로 반환 (inges, VLM 응답의 `[YEAR: ...]` prefix를 떼어내 (year_label, markdown_table) 반환.     prefix 없거, 페이지 이미지 1장을 VLM에 던져 year dict 1개 반환. 표 없으면 None.     VLM 호출 실패 시 예외를 그대로 위로 던진다 (+17 more)

### Community 7 - "Semiconductor Curriculum"
Cohesion: 0.18
Nodes (16): 반도체정보공학전공 2015~2016학년도 교과과정, 반도체정보공학전공 2017~2018학년도 교과과정, 반도체정보공학전공 2019~2020학년도 교과과정, 반도체정보공학전공 2021~2022학년도 교과과정, 반도체정보공학전공 2023~2026학년도 교과과정, 전공선택, 전공필수, 전기공학전공 2011~2016학년도 교과과정 (+8 more)

### Community 8 - "User Profile"
Cohesion: 0.14
Nodes (11): get_user(), users 테이블에서 student_id 조회. interests는 콤마문자열을 list로 풀어서 돌려준다., profile UPSERT. interests는 콤마 문자열로 저장., upsert_user(), get_current_user(), 페이지 공용 상수, 데이터 변환 헬퍼, 사용자 컨텍스트., get_documents 결과 row → notice dict., 현재 사용자 프로필. DB에 없으면 기본값으로 시드한 뒤 반환. (+3 more)

### Community 9 - "Board Notice Crawler"
Cohesion: 0.24
Nodes (4): BoardNoticeConfig, BoardNoticeCrawler, 제목·본문 등을 합쳐 XLSX_KEYWORDS 중 하나라도 포함하면 True., xlsx_relevant()

### Community 10 - "Curriculum Ingest Script"
Cohesion: 0.21
Nodes (12): source 테이블에 UPSERT 후 id 반환., upsert_source(), _expand_years(), ingest(), _lead_sentence(), main(), _pseudo_url(), data/curriculums/**/<key>*.pdf 를 DB에 적재한다.  정책: 커리큘럼은 사람이 손으로 정제한 PDF를 data/curr (+4 more)

### Community 11 - "Embedding Module"
Cohesion: 0.31
Nodes (9): chunk_text(), embed_chunks(), embed_query(), get_embeddings(), _get_splitter(), provider 토글에 따라 OpenAI/Gemini 임베딩 클라이언트를 돌려준다.      두 provider 모두 결과 차원을 EMBEDDI, RecursiveCharacterTextSplitter 싱글톤. lazy import로 cold start 영향 회피., 한국어 공지 기준 의미 단위 분할. CHUNK_SIZE 자 상한, CHUNK_OVERLAP 자 overlap. (+1 more)

### Community 12 - "Home Page UI"
Cohesion: 0.38
Nodes (6): _d_label(), 홈 페이지. 관심사·학과 기반 추천 3건 + 마감 임박 공지., 관심키워드 매칭 + 학과 일치 + 마감 임박도로 점수 산출.      임베딩 호출 없이 결정적으로 동작. 반환: (score, matched_k, _render_deadline_row(), _render_recommendation_card(), _score_notice()

### Community 13 - "Reranker"
Cohesion: 0.38
Nodes (6): _get_reranker(), BGE-reranker 로컬 cross-encoder 재정렬.  graph.py의 _retrieve에서 vector top-N 후보를 받아 to, 앱 부팅 시 호출. 모델 로드 + 더미 forward 1회로 첫 질문 latency 제거., 각 passage의 relevance score 리스트 반환 (입력 순서 유지, sigmoid로 0~1 정규화)., rerank_scores(), warmup()

### Community 14 - "Claude Settings"
Cohesion: 0.40
Nodes (4): permissions, allow, worktree, bgIsolation

## Knowledge Gaps
- **65 isolated node(s):** `project`, `working_directory`, `last_updated`, `vector_db`, `embedding` (+60 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ingest()` connect `Curriculum Ingest Script` to `Embedding Module`, `DB Schema & Queries`, `Curriculum Parser (VLM)`?**
  _High betweenness centrality (0.150) - this node is a cross-community bridge._
- **Why does `parse()` connect `Curriculum Parser (VLM)` to `Curriculum Ingest Script`?**
  _High betweenness centrality (0.131) - this node is a cross-community bridge._
- **Why does `_page_to_year()` connect `Curriculum Parser (VLM)` to `Document Parser`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `ingest()` (e.g. with `embed_chunks()` and `upsert_source()`) actually correct?**
  _`ingest()` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `parse()` (e.g. with `main()` and `test_parse_filters_no_table_pages()`) actually correct?**
  _`parse()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `RAG 파이프라인 튜닝 상수와 환경 변수 일괄 관리.  기존에 embed.py / graph.py / rerank.py / db.py / mod`, `provider 토글에 따라 OpenAI/Gemini 임베딩 클라이언트를 돌려준다.      두 provider 모두 결과 차원을 EMBEDDI`, `RecursiveCharacterTextSplitter 싱글톤. lazy import로 cold start 영향 회피.` to the rest of the system?**
  _156 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Document Parser` be split into smaller, more focused modules?**
  _Cohesion score 0.07087486157253599 - nodes in this community are weakly interconnected._