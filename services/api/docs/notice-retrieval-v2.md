# 공지 수집·검색 v2 설계

## 목표

공지 원문을 먼저 구조화하고, Codmes의 대화 모델이 질문 의미에 따라 Scan 또는
Deep MCP 도구를 선택한다. KNU 서버는 질문을 키워드로 다시 분류하거나 별도의
LLM router를 호출하지 않는다.

역할은 다음처럼 분리한다.

- Codmes LLM: 질문 의도 판단, MCP 도구 선택, 구조화 인자 생성, 최종 답변
- KNU Scan: 메타데이터 필터·정렬·집계
- KNU Deep: 제한된 후보 범위에서 임베딩 검색·리랭킹·근거 반환
- PostgreSQL: 날짜·대상·보존 상태를 포함한 사실 계산

## 구현 순서

1. 통합 공지 스키마와 다중 일정·대상·신청정보 저장
2. refine 결과에 원문 근거와 신뢰도 포함
3. 최근 24개월 전체 보존과 과거 경량 보관
4. `knu_list_notices` Scan 도구
5. `knu_search_notice_details` Deep 도구
6. Codmes의 MCP `structuredContent` 전달
7. 기존 `search_knu_notices` 제거와 Marketplace 새 버전 배포

## 통합 데이터 모델

### `notice`

공지의 정체성과 원문을 저장한다. 카테고리는 테이블 이름이 아니라 인덱스 가능한
열이다.

- source, URL, 제목
- 원문과 본문
- 대표 카테고리와 복수 topic
- 반복 공지 식별자 `series_key`
- 게시일·수정일·수집일
- 요약
- 고정 여부와 보관 상태
- 추출기 버전과 전체 신뢰도

### `notice_period`

한 공지에 여러 일정을 저장한다.

- `application`: 신청
- `document_submission`: 서류 제출
- `result_announcement`: 결과 발표
- `event`: 행사
- `registration`: 등록
- `payment`: 납부
- `other`: 기타

날짜와 함께 원문 근거 `source_text`, 추출 신뢰도, 연도 추론 여부를 저장한다.
`open` 여부는 저장하지 않고 조회 기준일과 신청 기간을 비교해 계산한다.

### `notice_audience`

대상 조건을 복수 행으로 저장한다.

- `department`
- `grade`
- `enrollment_status`
- `eligibility`

각 조건에도 원문 근거와 신뢰도를 저장한다.

### `notice_application`

신청 방법, 신청 URL, 제출서류, 문의처, 장소, 혜택을 저장한다.

### `notice_asset`, `notice_chunk`

첨부파일과 Deep 검색용 임베딩 청크를 공지 ID에 직접 연결한다. 카테고리별 동적
테이블은 v2 런타임에서 사용하지 않는다.

## 보존 정책

기본 전체 보존 기간은 게시일 기준 24개월이다.

### Hot

- 최근 24개월
- 현재 고정 공지
- 관리자가 영구 보존한 공지
- 원문·첨부 추출문·임베딩 청크 유지

### Archived

24개월이 지났고 고정·영구 보존 대상이 아닌 공지는 다음만 유지한다.

- 제목, URL, 출처, 카테고리
- 게시일, 구조화 일정·대상
- 요약, topic, `series_key`
- 원문 해시

원문·첨부 추출문·임베딩 청크는 제거한다. 명시적인 과거 질문에서만 메타데이터
검색 대상으로 사용한다.

마감 직후 삭제하지 않는다. 접수 종료 여부는 Scan 필터에만 사용하며, 보관 전환은
24개월 기준으로만 수행한다.

## MCP 도구

### `knu_list_notices`

목록·개수·정렬을 위한 Scan 도구다. 임베딩과 리랭커를 호출하지 않는다.

예시 인자:

```json
{
  "category": "장학",
  "status": "open",
  "timeScope": "current",
  "department": "컴퓨터공학과",
  "grade": 3,
  "year": 2026,
  "sort": "end_date",
  "offset": 0
}
```

서버는 조회 기준일을 직접 정하고 `total`을 전체 조건 결과로 계산한다. 페이지 크기는
서버 정책이며 `total`에 영향을 주지 않는다.

### `knu_search_notice_details`

구체적인 날짜·자격·절차·첨부 근거를 찾는 Deep 도구다.

예시 인자:

```json
{
  "query": "2026학년도 2학기 수강신청 재수강 주의사항",
  "category": "수강",
  "timeScope": "current",
  "year": 2026,
  "noticeIds": []
}
```

KNU 서버는 구조화 필터를 벡터 검색 전에 적용한다. 기본 내부 정책은 후보 청크 50개,
근거 청크 5개, 지원 문서 3개다. 이 값은 MCP 사용자 인자가 아니다.

### Hybrid

별도 Hybrid 도구를 만들지 않는다. Codmes 모델이 Scan으로 후보 ID를 받은 뒤 Deep에
그 ID를 전달한다.

## 시간 범위

- `current`: 기본값. Hot 공지만 검색
- `historical`: Archived 메타데이터 검색
- `all`: 비교 질문에서 Hot과 Archived 검색

KNU 서버는 질문 문장에서 연도나 키워드를 추출하지 않는다. Codmes 모델이 명시적인
도구 인자로 전달하고 KNU 서버는 enum·연도·ID와 접근 권한을 검증한다.

## 전환 원칙

- 새 스키마 생성은 비파괴적으로 수행한다.
- 기존 카테고리별 테이블 데이터는 명시적인 마이그레이션 또는 재수집 선택 후
  v2로 전환한다.
- v2 읽기·쓰기가 검증되기 전에는 기존 테이블을 삭제하지 않는다.
- 전환 완료 후 기존 동적 테이블 생성·조회 코드는 제거한다.
