KNU AI Assistant — 전체 RAG 흐름 설명

==================================================
1. 크롤링 단계
==================================================

크롤러:
CRAWLERS/methods/board_notice.py

예시 공지:

제목:
2026 AWS 클라우드 취업 특강 신청 안내

본문:
- 신청기간: 5월 20일 ~ 5월 30일
- 대상: 재학생
- 장소: 공학관 101호
- AWS 현직자 멘토링 진행

첨부:
AWS_특강_상세안내.pdf

크롤러가 수집하는 구조:

{
  "title": "...",
  "url": "...",
  "date": "...",

  # legacy full text
  "content": "...",

  # 핵심 분리 구조
  "body_content": "...",

  "attachment_contents": [
    {
      "name": "AWS_특강_상세안내.pdf",
      "text": "AWS 자격증 로드맵 ... 클라우드 엔지니어 ..."
    }
  ],

  "assets": [...],
}

핵심:
- 본문(body)
- 첨부파일(attachment)

을 분리 저장한다.


==================================================
2. attachment 추출
==================================================

EXTRACTORS/attachments.py

PDF/HWP/HWPX/XLSX/이미지 등을 텍스트로 추출.

예:

AWS 자격증
Solutions Architect
클라우드 포트폴리오
현직자 멘토링


==================================================
3. refine 단계
==================================================

refine.py

LLM이 다음 메타데이터를 생성:

- category
- keywords
- summary
- target
- start_date
- end_date

예:

MetadataSchema(
  category="취업(진로)",
  target=["재학생"],
  keywords=["AWS", "클라우드", "멘토링"],
  summary="AWS 현직자 특강 ..."
)

중요:
refine는 메타데이터 생성 목적이다.

긴 attachment 원문 전체를 항상 넣는 것이 아니라,
context budget 기반으로 필요한 만큼만 사용한다.

하지만:
- 저장(storage)
- embedding
- retrieval

에는 원문 전체가 유지된다.


==================================================
4. DB 저장
==================================================

db.py

documents 테이블 저장:

- title
- url
- content
- summary
- metadata

등 저장.

그리고 실제 retrieval 핵심은:

document_chunk 테이블

이다.


==================================================
5. embedding/chunking
==================================================

EMBEDDING/embed.py

body와 attachment를 각각 chunk화.

예:

[body chunk]
신청기간: ...
AWS 현직자 멘토링 ...

[attachment chunk]
AWS 자격증 로드맵
클라우드 엔지니어 포트폴리오

즉 attachment도 일반 chunk와 동일하게 retrieval 대상이 된다.


==================================================
6. 사용자 질문
==================================================

사용자 질문:

"AWS 자격증 관련 특강 있어?"


==================================================
7. router 단계 (카테고리 분류 + query expansion)
==================================================

RETRIEVAL/graph.py
router_node()

LLM이 질문을 분석해:

1. categories
2. expanded_query

를 생성한다.

예:

입력 질문:
"AWS 자격증 관련 특강 있어?"

router 결과:

{
  "categories": ["취업(진로)"],
  "expanded_query":
    "AWS 자격증 클라우드 취업특강 멘토링 신청 안내",
}

즉:
- 카테고리 분류
- 검색용 query expansion

을 먼저 수행한다.

중요:
이 categories는 실제 retrieval filter로 사용된다.

즉:

search_chunks(
    ...,
    categories=["취업(진로)"]
)

형태로 들어간다.

그래서:
- 장학
- 수강
- 일반

등 다른 카테고리 chunk는
초기 vector retrieval 후보에서 제외 가능.

현재 흐름:

사용자 질문
→ router(category + expanded_query)
→ category-filtered vector search
→ rerank
→ answer


==================================================
8. query embedding
==================================================

expanded_query를 embedding:

embed_query(query)

vector 생성.


==================================================
9. vector retrieval
==================================================

DB chunk 테이블 전체에서:

vector similarity top-K

검색.

예시 상황:

본문에는:

"AWS 특강"

정도만 있고,

실제:

"AWS 자격증 로드맵"
"클라우드 엔지니어"

내용은 attachment에만 존재한다고 가정.

retrieval 결과:

1위: attachment chunk
2위: attachment chunk
3위: body chunk

가능.

즉:

첨부파일 chunk가 실제 retrieval 핵심 evidence가 될 수 있다.


==================================================
10. rerank
==================================================

RETRIEVAL/rerank.py

CrossEncoder rerank 수행.

예:

| chunk | rerank |
|---|---|
| attachment AWS 자격증 로드맵 | 0.98 |
| attachment 클라우드 포트폴리오 | 0.95 |
| body 신청기간 | 0.62 |

즉 attachment evidence가 최종 승리 가능.


==================================================
11. evidence chunk 선정
==================================================

RERANK_TOP_N=8

상위 8개 chunk를 evidence chunk로 선정.

예:

evidence chunk 1:
AWS 자격증 로드맵 ...

evidence chunk 2:
클라우드 엔지니어 포트폴리오 ...

이 evidence chunk는 answerer prompt 최상단에 직접 들어간다.


==================================================
12. support document 선정
==================================================

rerank 결과를 문서 단위로 병합.

예:

"AWS 특강 공지"

문서가:
- top1 chunk
- top2 chunk
- top5 chunk

를 가지고 있으면,

문서 대표 score는:
가장 높은 chunk score 사용.


==================================================
13. context packing
==================================================

현재 전략:

evidence-first
+
adaptive support packing

항상 유지:
- 핵심 evidence chunk

그리고 남는 budget에 따라:
- support document body
- summary
- matched chunk

를 최대한 stuffing.

현재 구조:

1등 support document:
- body full 우선

2~3등 support document:
- summary + matched chunk 우선
- budget 충분하면 body도 많이 유지

또한:
attachment giant stuffing은 금지.

즉:
첨부파일 전체를 통째로 answer prompt에 넣는 것이 아니라,

retrieval된 attachment chunk만
evidence로 활용한다.


==================================================
14. answerer prompt 실제 형태
==================================================

대략 이런 구조:

# 핵심 검색 청크

[1] AWS 특강 안내
URL: ...

AWS 자격증 로드맵 ...

[2] AWS 특강 안내
URL: ...

클라우드 엔지니어 포트폴리오 ...

---

[관련 문서]

제목: AWS 특강 안내
접수기간: ...
본문:
...


==================================================
15. answer 생성
==================================================

LLM 답변 예시:

"AWS 자격증 및 클라우드 엔지니어 진로 관련 특강이 있습니다.
현직자 멘토링과 포트폴리오 안내가 포함되어 있으며..."


==================================================
16. verifier (optional)
==================================================

ENABLE_VERIFIER=true

일 때만 verifier 실행.

현재 verifier 역할:

- grounded 여부
- hallucination 여부
- fidelity score

검사.

기본값은 false.
